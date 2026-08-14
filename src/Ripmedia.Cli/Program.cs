using System.Text.Json;
using Ripmedia.Core;
using Spectre.Console;
using Spectre.Console.Rendering;

return await Application.RunAsync(args);

internal static class Application
{
    private static readonly HttpClient Http = new();
    public static async Task<int> RunAsync(string[] args)
    {
        var store = new SettingsStore(); var settings = await store.LoadAsync();
        if (args.Length == 0 || args[0] is "help" or "--help" or "-h") { Help(); return 0; }
        var command = args[0].ToLowerInvariant();
        if (command is not ("download" or "info" or "cookies" or "config" or "update" or "version")) return await DownloadAsync(args, settings, store);
        return command switch
        {
            "download" => await DownloadAsync(args[1..], settings, store),
            "info" => await InfoAsync(args[1..], settings),
            "cookies" => await CookiesAsync(args[1..], settings, store),
            "config" => await ConfigAsync(args[1..], settings, store),
            "update" => await UpdateAsync(),
            "version" => Version(),
            _ => 2
        };
    }

    private static async Task<int> DownloadAsync(string[] args, RipmediaSettings settings, SettingsStore store)
    {
        DownloadRequest request;
        try { request = ParseDownload(args); } catch (ArgumentException error) { Error(error.Message); return 2; }
        if (request.Inputs.Count == 0) { Error("Supply at least one URL or URL file."); return 2; }
        var pipeline = new DownloadPipeline(new YtDlpClient(), new MediaTagger(Http));
        DownloadResult result;
        try
        {
            if (request.Quiet || request.PrintPath)
                result = await pipeline.RunAsync(request, settings, null, null, CancellationToken.None);
            else result = await RunWithLiveUiAsync(pipeline, request, settings);
        }
        catch (Exception error) { Error(error.Message); return 1; }
        foreach (var path in result.Paths) Console.WriteLine(path);
        return result.Paths.Count > 0 ? 0 : 1;
    }

    private static async Task<DownloadResult> RunWithLiveUiAsync(DownloadPipeline pipeline, DownloadRequest request, RipmediaSettings settings)
    {
        var rows = new List<StageResult>(); var percent = 0d;
        DownloadResult? result = null;
        await AnsiConsole.Live(Render()).AutoClear(false).StartAsync(async context =>
        {
            result = await pipeline.RunAsync(request, settings,
                stage => { rows.Add(stage); context.UpdateTarget(Render()); },
                progress => { if (progress.Percentage is not null) percent = progress.Percentage.Value; context.UpdateTarget(Render()); }, CancellationToken.None);
            context.UpdateTarget(Render());
        });
        return result!;
        IRenderable Render()
        {
            var chart = new BarChart().Width(60).AddItem("Downloading", Math.Clamp(percent, 0, 100), Color.Cyan1);
            IRenderable text = rows.Count == 0 ? new Markup("[grey]Preparing…[/]") : new Rows(rows.Select(row => (IRenderable)new Markup($"[{(row.Success ? "green" : "red")}]{(row.Success ? "✓" : "×")}[/] {Markup.Escape(row.Name)}" + (string.IsNullOrWhiteSpace(row.Detail) ? string.Empty : $" [grey]{Markup.Escape(Shorten(row.Detail))}[/]"))));
            return new Rows(chart, text);
        }
    }

    private static async Task<int> InfoAsync(string[] args, RipmediaSettings settings)
    {
        var json = args.Contains("--json", StringComparer.OrdinalIgnoreCase); var formats = args.Contains("--formats", StringComparer.OrdinalIgnoreCase);
        var url = args.FirstOrDefault(arg => !arg.StartsWith('-'));
        if (url is null) { Error("Supply a URL."); return 2; }
        try
        {
            var client = new YtDlpClient(); var item = await client.InspectAsync(url, settings.CookieFile, settings.BrowserCookieProfile?.YtDlpValue, false, CancellationToken.None);
            if (json) Console.WriteLine(JsonSerializer.Serialize(item, new JsonSerializerOptions { WriteIndented = true }));
            else
            {
                var table = new Table().Border(TableBorder.Rounded).AddColumn("Field").AddColumn("Value");
                table.AddRow("Title", item.Title ?? "unknown"); table.AddRow("Provider", item.Provider.ToString()); table.AddRow("Type", item.Kind.ToString()); table.AddRow("Artist", item.Artist ?? "unknown"); table.AddRow("Format", item.Extension ?? "unknown");
                AnsiConsole.Write(table);
            }
            if (formats)
            {
                var output = await client.ListFormatsAsync(url, settings.CookieFile, settings.BrowserCookieProfile?.YtDlpValue, CancellationToken.None);
                foreach (var line in output.StandardOutput) Console.WriteLine(line);
                if (output.ExitCode != 0) return 1;
            }
            return 0;
        }
        catch (Exception error) { Error(error.Message); return 1; }
    }

    private static async Task<int> CookiesAsync(string[] args, RipmediaSettings settings, SettingsStore store)
    {
        if (args.FirstOrDefault()?.Equals("clear", StringComparison.OrdinalIgnoreCase) == true)
        {
            settings.BrowserCookieProfile = null; await store.SaveAsync(settings); AnsiConsole.MarkupLine("[green]Browser cookie profile cleared.[/]"); return 0;
        }
        var profiles = CookieProfiles.Discover();
        if (args.FirstOrDefault()?.Equals("list", StringComparison.OrdinalIgnoreCase) == true)
        {
            foreach (var profile in profiles) Console.WriteLine(profile); return profiles.Count == 0 ? 1 : 0;
        }
        if (profiles.Count == 0) { Error("No supported browser profiles with cookies were found."); return 1; }
        var selected = profiles.Count == 1 ? profiles[0] : AnsiConsole.Prompt(new SelectionPrompt<BrowserCookieProfile>().Title("[cyan]Select browser profile[/]").PageSize(12).AddChoices(profiles));
        settings.BrowserCookieProfile = selected; await store.SaveAsync(settings); AnsiConsole.MarkupLine($"[green]Using[/] {Markup.Escape(selected.ToString())}"); return 0;
    }

    private static async Task<int> ConfigAsync(string[] args, RipmediaSettings settings, SettingsStore store)
    {
        if (args.Length == 0) { Console.WriteLine(JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true })); return 0; }
        if (args[0].Equals("path", StringComparison.OrdinalIgnoreCase)) { Console.WriteLine(store.SettingsPath); return 0; }
        var offset = args[0].Equals("set", StringComparison.OrdinalIgnoreCase) ? 1 : 0;
        var expression = args.Skip(offset).FirstOrDefault();
        if (expression is null) { Error("Use config set key=value."); return 2; }
        var pair = expression.Split('=', 2); if (pair.Length != 2) { Error("Use config set key=value."); return 2; }
        switch (pair[0].Trim().Replace("-", string.Empty, StringComparison.Ordinal).ToLowerInvariant())
        {
            case "outputdir": settings.OutputDirectory = pair[1].Trim(); break;
            case "speedunit": settings.SpeedUnit = pair[1].Trim(); break;
            case "showfilesize": settings.ShowFileSize = ParseBool(pair[1]); break;
            case "nocolor": settings.NoColor = ParseBool(pair[1]); break;
            case "cookies": settings.CookieFile = string.Equals(pair[1].Trim(), "none", StringComparison.OrdinalIgnoreCase) ? null : pair[1].Trim(); break;
            default: Error("Supported settings: output_dir, speed_unit, show_file_size, no_color, cookies."); return 2;
        }
        await store.SaveAsync(settings); AnsiConsole.MarkupLine("[green]Configuration saved.[/]"); return 0;
    }

    private static async Task<int> UpdateAsync()
    {
        try { var version = await new ReleaseUpdater(Http).UpdateAsync(CancellationToken.None); AnsiConsole.MarkupLine($"[green]Updated to[/] {Markup.Escape(version)}"); return 0; }
        catch (Exception error) { Error(error.Message); return 1; }
    }
    private static int Version() { Console.WriteLine(typeof(Application).Assembly.GetName().Version?.ToString(3) ?? "0.1.0"); return 0; }

    private static DownloadRequest ParseDownload(string[] args)
    {
        var inputs = new List<string>(); string? output = null; string? format = null; string? cookies = null; string? browser = null; var audio = false; var noPlaylist = false; var quiet = false; var verbose = false; var debug = false; var printPath = false; var noColor = false; string? speed = null;
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i]; string Value() => ++i < args.Length ? args[i] : throw new ArgumentException($"{arg} requires a value.");
            switch (arg)
            {
                case "--output-dir": output = Value(); break; case "--format": format = Value(); break; case "--cookies": cookies = Value(); break; case "--cookies-from-browser": browser = Value(); break; case "--speed-unit": speed = Value(); break;
                case "--audio": audio = true; break; case "--mp3": format = "mp3"; break; case "--no-playlist": noPlaylist = true; break; case "--quiet": quiet = true; break; case "--verbose": case "-v": verbose = true; break; case "--debug": debug = true; break; case "--print-path": printPath = true; break; case "--no-color": noColor = true; break;
                default: if (arg.StartsWith('-')) throw new ArgumentException($"Unknown option: {arg}"); else inputs.Add(arg); break;
            }
        }
        return new DownloadRequest(inputs, output, audio, FormatRules.Normalize(format), noPlaylist, cookies, browser, quiet, verbose, debug, printPath, noColor, speed);
    }
    private static bool ParseBool(string value) => value.Trim().ToLowerInvariant() is "1" or "true" or "yes" or "on";
    private static string Shorten(string text) => text.Length <= 72 ? text : text[..69] + "...";
    private static void Error(string message) => AnsiConsole.MarkupLine($"[red]Error:[/] {Markup.Escape(message)}");
    private static void Help() => AnsiConsole.WriteLine("ripmedia — source-format-preserving media downloader\n\nUsage: ripmedia <url> [flags]\n       ripmedia download <url> [flags]\n       ripmedia info <url> [--json] [--formats]\n       ripmedia cookies [list|clear]\n       ripmedia config [path|set key=value]\n       ripmedia update\n\nFlags: --audio --mp3 --format <ext> --output-dir <path> --no-playlist --cookies <file> --cookies-from-browser <spec>");
}
