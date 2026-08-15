using System.Text.Json;
using System.Diagnostics;
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
        if (command is not ("download" or "info" or "cookies" or "config" or "update" or "version" or "webhost")) return await DownloadAsync(args, settings, store);
        return command switch
        {
            "download" => await DownloadAsync(args[1..], settings, store),
            "info" => await InfoAsync(args[1..], settings),
            "cookies" => await CookiesAsync(args[1..], settings, store),
            "config" => Config(args[1..], store),
            "update" => await UpdateAsync(),
            "version" => Version(),
            "webhost" => await WebHost.RunAsync(args[1..], settings),
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
        var title = "media"; var speed = (string?)null; var eta = (string?)null;
        var stages = new List<StageResult>();
        DownloadResult? result = null;
        await AnsiConsole.Progress()
            .AutoClear(false)
            .Columns(
                new SpinnerColumn(Spinner.Known.Ascii)
                    .Style(Style.Parse("#d6a1ac"))
                    .CompletedStyle(Style.Parse("#b8ceb8")),
                new TaskDescriptionColumn(),
                new ProgressBarColumn()
                    .CompletedStyle(Style.Parse("#d6a1ac"))
                    .FinishedStyle(Style.Parse("#b8ceb8"))
                    .RemainingStyle(Style.Parse("#5e555a")),
                new PercentageColumn { Style = Style.Parse("#e0c0c6"), CompletedStyle = Style.Parse("#b8ceb8") },
                new DownloadStatsColumn(() => FormatDownloadStats(speed, eta)))
            .UseRenderHook((progress, _) => RenderStages(progress, stages))
            .StartAsync(async context =>
        {
            var task = context.AddTask("[#d6a1ac]Preparing[/] media", maxValue: 100);
            result = await pipeline.RunAsync(request, settings,
                stage =>
                {
                    stages.Add(stage);
                    if (!string.IsNullOrWhiteSpace(stage.Detail)) title = UiText.Truncate(stage.Detail, 48);
                    task.Description(Describe(stage.Success ? stage.Name : $"{stage.Name} failed", title));
                },
                progress =>
                {
                    task.IsIndeterminate(progress.IsProcessing);
                    if (progress.IsProcessing)
                    {
                        speed = null; eta = null;
                        task.Description(Describe(progress.Activity!, title));
                        return;
                    }
                    if (progress.Percentage is not null) task.Value(Math.Clamp(progress.Percentage.Value, 0, 100));
                    if (!string.IsNullOrWhiteSpace(progress.Speed)) speed = progress.Speed;
                    if (!string.IsNullOrWhiteSpace(progress.Eta)) eta = progress.Eta;
                    if (progress.Percentage is not null || progress.Speed is not null || progress.Eta is not null)
                        task.Description(Describe("Downloading", title));
                }, CancellationToken.None);
            task.IsIndeterminate(false);
            task.Value(100);
            speed = null; eta = null;
            task.Description(result.Paths.Count > 0 ? "[#b8ceb8]Download complete[/]" : "[#d69ba6]Download finished with errors[/]");
            task.StopTask();
        });
        return result!;
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

    private static int Config(string[] args, SettingsStore store)
    {
        if (args.Length != 0)
        {
            Error("The config command does not accept arguments.");
            return 2;
        }
        try
        {
            Process.Start(new ProcessStartInfo { FileName = store.SettingsPath, UseShellExecute = true });
            return 0;
        }
        catch (Exception error)
        {
            Error($"Could not open the configuration file: {error.Message}");
            return 1;
        }
    }

    private static async Task<int> UpdateAsync()
    {
        try { var version = await new ReleaseUpdater(Http).UpdateAsync(CancellationToken.None); AnsiConsole.MarkupLine($"[green]Updated to[/] {Markup.Escape(version)}"); return 0; }
        catch (Exception error) { Error(error.Message); return 1; }
    }
    private static int Version() { Console.WriteLine(typeof(Application).Assembly.GetName().Version?.ToString(3) ?? "0.1.0"); return 0; }

    internal static DownloadRequest ParseDownload(string[] args)
    {
        var inputs = new List<string>(); string? output = null; string? format = null; string? cookies = null; string? browser = null; var audio = false; var noPlaylist = false; var quiet = false; var verbose = false; var debug = false; var printPath = false; var noColor = false; string? speed = null;
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i]; string Value() => ++i < args.Length ? args[i] : throw new ArgumentException($"{arg} requires a value.");
            switch (arg)
            {
                case "--output-dir": output = Value(); break;
                case "--format": format = Value(); break;
                case "--cookies": cookies = Value(); break;
                case "--cookies-from-browser": browser = Value(); break;
                case "--speed-unit": speed = Value(); break;
                case "--audio": audio = true; break;
                case "--mp3": format = "mp3"; break;
                case "--mp4": format = "mp4"; break;
                case "--no-playlist": noPlaylist = true; break;
                case "--quiet": quiet = true; break;
                case "--verbose":
                case "-v": verbose = true; break;
                case "--debug": debug = true; break;
                case "--print-path": printPath = true; break;
                case "--no-color": noColor = true; break;
                default: if (arg.StartsWith('-')) throw new ArgumentException($"Unknown option: {arg}"); else inputs.Add(arg); break;
            }
        }
        return new DownloadRequest(inputs, output, audio, FormatRules.Normalize(format), noPlaylist, cookies, browser, quiet, verbose, debug, printPath, noColor, speed);
    }
    private static IRenderable RenderStages(IRenderable progress, IReadOnlyList<StageResult> stages)
    {
        var rows = new List<IRenderable> { progress };
        rows.AddRange(stages.Select(stage => (IRenderable)new Markup($"[{(stage.Success ? "#b8ceb8" : "#d69ba6")}]{(stage.Success ? "✓" : "×")}[/] {Markup.Escape(stage.Name)}" + (string.IsNullOrWhiteSpace(stage.Detail) ? string.Empty : $" [#a99ba0]{Markup.Escape(UiText.Truncate(stage.Detail))}[/]"))));
        return new Rows(rows);
    }
    private static string Describe(string action, string title) => $"[#d6a1ac]{Markup.Escape(action)}[/] {Markup.Escape(title)}";
    private static string FormatDownloadStats(string? speed, string? eta)
    {
        var transfer = new List<string>();
        if (!string.IsNullOrWhiteSpace(speed)) transfer.Add(speed);
        if (!string.IsNullOrWhiteSpace(eta)) transfer.Add($"ETA {eta}");
        return string.Join(" · ", transfer);
    }
    private static void Error(string message) => AnsiConsole.MarkupLine($"[red]Error:[/] {Markup.Escape(message)}");
    private static void Help() => AnsiConsole.WriteLine("ripmedia — source-format-preserving media downloader\n\nUsage: ripmedia <url> [flags]\n       ripmedia download <url> [flags]\n       ripmedia info <url> [--json] [--formats]\n       ripmedia cookies [list|clear]\n       ripmedia config\n       ripmedia webhost\n       ripmedia update\n\nFlags: --audio --mp3 --mp4 --format <ext> --output-dir <path> --no-playlist --cookies <file> --cookies-from-browser <spec>");
}

internal sealed class DownloadStatsColumn(Func<string> getText) : ProgressColumn
{
    protected override bool NoWrap => true;
    public override IRenderable Render(RenderOptions options, ProgressTask task, TimeSpan delta) => new Markup($"[#a99ba0]{Markup.Escape(getText())}[/]");
    public override int? GetColumnWidth(RenderOptions options) => 24;
}
