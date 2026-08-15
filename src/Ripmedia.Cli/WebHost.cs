using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.Json;
using Ripmedia.Core;
using Spectre.Console;

internal static class WebHost
{
    private const string Address = "http://127.0.0.1:4747/";
    private static readonly ConcurrentDictionary<string, WebDownload> Downloads = new();
    private static readonly ConcurrentDictionary<string, StreamWriter> EventClients = new();
    private static readonly SemaphoreSlim EventWriteLock = new(1, 1);
    private static readonly HttpClient Http = new();

    public static async Task<int> RunAsync(string[] args, RipmediaSettings settings)
    {
        if (args.Length != 0)
        {
            AnsiConsole.MarkupLine("[red]Error:[/] The webhost command does not accept arguments.");
            return 2;
        }

        using var listener = new HttpListener();
        listener.Prefixes.Add(Address);
        try { listener.Start(); }
        catch (HttpListenerException error)
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Could not start the web interface: {Markup.Escape(error.Message)}");
            return 1;
        }

        try
        {
            Process.Start(new ProcessStartInfo { FileName = Address, UseShellExecute = true });
            AnsiConsole.MarkupLine($"[#b8ceb8]Web interface running[/] at [#d6a1ac]{Address}[/]. Press Ctrl+C to stop.");
            while (listener.IsListening)
            {
                var context = await listener.GetContextAsync();
                _ = HandleAsync(context, settings);
            }
        }
        catch (HttpListenerException) when (!listener.IsListening) { }
        catch (Exception error)
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Web interface stopped: {Markup.Escape(error.Message)}");
            return 1;
        }

        return 0;
    }

    private static async Task HandleAsync(HttpListenerContext context, RipmediaSettings settings)
    {
        try
        {
            if (context.Request.HttpMethod == "GET" && context.Request.Url?.AbsolutePath == "/")
                await SendAsync(context.Response, "text/html; charset=utf-8", DashboardPage());
            else if (context.Request.HttpMethod == "POST" && context.Request.Url?.AbsolutePath == "/download")
                await QueueDownloadAsync(context, settings);
            else if (context.Request.HttpMethod == "GET" && context.Request.Url?.AbsolutePath.StartsWith("/download/", StringComparison.Ordinal) == true)
                await SendStatusPageAsync(context);
            else if (context.Request.HttpMethod == "GET" && context.Request.Url?.AbsolutePath == "/api/downloads")
                await SendDownloadStatusAsync(context);
            else if (context.Request.HttpMethod == "GET" && context.Request.Url?.AbsolutePath == "/events")
                await ListenForEventsAsync(context);
            else if (context.Request.HttpMethod == "GET" && context.Request.Url?.AbsolutePath.StartsWith("/open/", StringComparison.Ordinal) == true)
                await OpenDownloadAsync(context);
            else
                await SendAsync(context.Response, "text/plain; charset=utf-8", "Not found.", HttpStatusCode.NotFound);
        }
        catch (Exception error)
        {
            try { await SendAsync(context.Response, "text/html; charset=utf-8", StatusPage(new(DateTimeOffset.UtcNow, true, false, null, error.Message, null, null, null, []), false), HttpStatusCode.InternalServerError); }
            catch (HttpListenerException) { }
        }
        finally { context.Response.Close(); }
    }

    private static async Task QueueDownloadAsync(HttpListenerContext context, RipmediaSettings settings)
    {
        using var reader = new StreamReader(context.Request.InputStream, context.Request.ContentEncoding ?? Encoding.UTF8);
        var commands = ParseFormValues(await reader.ReadToEndAsync(), "url")
            .SelectMany(value => value.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
        var requests = new List<DownloadRequest>();
        try
        {
            foreach (var command in commands)
            {
                var request = Application.ParseDownload(SplitCommandLine(command));
                if (request.Inputs.Count == 0) throw new ArgumentException("Paste a URL followed by any download flags.");
                requests.Add(request);
            }
        }
        catch (ArgumentException error)
        {
            await SendAsync(context.Response, "text/html; charset=utf-8", StatusPage(new(DateTimeOffset.UtcNow, true, false, null, error.Message, null, null, null, []), false), HttpStatusCode.BadRequest);
            return;
        }
        if (requests.Count == 0)
        {
            await SendAsync(context.Response, "text/html; charset=utf-8", StatusPage(new(DateTimeOffset.UtcNow, true, false, null, "Paste a URL followed by any download flags.", null, null, null, []), false), HttpStatusCode.BadRequest);
            return;
        }
        var queue = new List<(DownloadRequest Request, Uri Url)>();
        foreach (var request in requests)
        {
            foreach (var input in request.Inputs)
            {
                if (!Uri.TryCreate(input, UriKind.Absolute, out var url) || url.Scheme is not ("http" or "https"))
                {
                    await SendAsync(context.Response, "text/html; charset=utf-8", StatusPage(new(DateTimeOffset.UtcNow, true, false, null, "Enter valid http(s) URLs followed by download flags.", null, null, null, []), false), HttpStatusCode.BadRequest);
                    return;
                }
                queue.Add((request, url));
            }
        }
        foreach (var item in queue)
        {
            var id = Guid.NewGuid().ToString("N");
            Downloads[id] = new(DateTimeOffset.UtcNow, false, false, item.Url.Host, "Preparing download…", null, null, null, []);
            _ = RunDownloadAsync(id, item.Request with { Inputs = [item.Url.AbsoluteUri], Quiet = true }, settings);
        }
        _ = BroadcastDownloadsAsync();
        context.Response.StatusCode = (int)HttpStatusCode.SeeOther;
        context.Response.RedirectLocation = "/";
        await context.Response.OutputStream.FlushAsync();
    }

    private static async Task RunDownloadAsync(string id, DownloadRequest request, RipmediaSettings settings)
    {
        try
        {
            var pipeline = new DownloadPipeline(new YtDlpClient(), new MediaTagger(Http));
            var result = await pipeline.RunAsync(request, settings.WithoutBrowserCookies(),
                stage => UpdateDownload(id, download => download with
                {
                    Message = stage.Success ? stage.Name : $"{stage.Name} failed",
                    Title = !string.IsNullOrWhiteSpace(stage.Detail) && (stage.Name is "Inspect" or "Download") ? stage.Detail
                        : !string.IsNullOrWhiteSpace(stage.Detail) && stage.Name == "Saved" ? Path.GetFileName(stage.Detail) : download.Title,
                    Progress = stage.Name == "Download" ? download.Progress : null,
                    Stages = [.. download.Stages, stage]
                }),
                progress => UpdateDownload(id, download => download with
                {
                    Message = "Downloading…",
                    Progress = progress.Percentage ?? download.Progress,
                    Speed = progress.Speed ?? download.Speed,
                    Eta = progress.Eta ?? download.Eta
                }), CancellationToken.None);
            var failed = result.Stages.LastOrDefault(stage => !stage.Success);
            UpdateDownload(id, download => result.Paths.Count > 0
                ? download with { Done = true, Ok = true, Message = "Download complete.", Progress = 100, Eta = null, Paths = result.Paths }
                : download with { Done = true, Ok = false, Message = failed?.Detail ?? "Download failed.", Eta = null });
        }
        catch (Exception error) { UpdateDownload(id, download => download with { Done = true, Ok = false, Message = error.Message, Eta = null }); }
    }

    private static Task SendStatusPageAsync(HttpListenerContext context)
    {
        var id = context.Request.Url!.AbsolutePath["/download/".Length..];
        return Downloads.TryGetValue(id, out var download)
            ? SendAsync(context.Response, "text/html; charset=utf-8", StatusPage(download, !download.Done))
            : SendAsync(context.Response, "text/html; charset=utf-8", StatusPage(new(DateTimeOffset.UtcNow, true, false, null, "Download not found.", null, null, null, []), false), HttpStatusCode.NotFound);
    }

    private static Task SendDownloadStatusAsync(HttpListenerContext context)
    {
        return SendJsonAsync(context.Response, DownloadStatusPayload());
    }

    private static async Task OpenDownloadAsync(HttpListenerContext context)
    {
        var id = context.Request.Url!.AbsolutePath["/open/".Length..];
        if (!Downloads.TryGetValue(id, out var download) || !download.Done || !download.Ok || download.Paths is not { Count: > 0 })
        {
            await SendAsync(context.Response, "text/plain; charset=utf-8", "Downloaded file not found.", HttpStatusCode.NotFound);
            return;
        }

        var path = download.Paths[0];
        if (!File.Exists(path))
        {
            await SendAsync(context.Response, "text/plain; charset=utf-8", "Downloaded file no longer exists.", HttpStatusCode.NotFound);
            return;
        }

        Process.Start(new ProcessStartInfo { FileName = "explorer.exe", Arguments = $"/select,\"{path}\"", UseShellExecute = true });
        context.Response.StatusCode = (int)HttpStatusCode.SeeOther;
        context.Response.RedirectLocation = "/";
        await context.Response.OutputStream.FlushAsync();
    }

    private static async Task ListenForEventsAsync(HttpListenerContext context)
    {
        var response = context.Response;
        response.StatusCode = (int)HttpStatusCode.OK;
        response.ContentType = "text/event-stream";
        response.SendChunked = true;
        response.KeepAlive = true;
        response.Headers[HttpResponseHeader.CacheControl] = "no-store";
        var id = Guid.NewGuid().ToString("N");
        await using var writer = new StreamWriter(response.OutputStream, new UTF8Encoding(false), 1024, true);
        EventClients[id] = writer;
        try
        {
            await WriteEventAsync(writer, $"retry: 1000\nevent: downloads\ndata: {JsonSerializer.Serialize(DownloadStatusPayload())}\n\n");
            while (true)
            {
                await Task.Delay(TimeSpan.FromSeconds(15));
                await WriteEventAsync(writer, ": keepalive\n\n");
            }
        }
        catch (HttpListenerException) { }
        catch (IOException) { }
        finally { EventClients.TryRemove(id, out _); }
    }

    private static object DownloadStatusPayload()
    {
        var downloads = Downloads.OrderByDescending(entry => entry.Value.StartedAt).Take(12).Select(entry => new
        {
            id = entry.Key,
            done = entry.Value.Done,
            ok = entry.Value.Ok,
            title = entry.Value.Title,
            message = entry.Value.Message,
            progress = entry.Value.Progress,
            speed = entry.Value.Speed,
            eta = entry.Value.Eta,
            paths = entry.Value.Paths
        });
        return new { downloads };
    }

    private static IEnumerable<string> ParseFormValues(string form, string name) => form.Split('&')
        .Select(part => part.Split('=', 2))
        .Where(part => part.Length == 2 && string.Equals(WebUtility.UrlDecode(part[0]), name, StringComparison.Ordinal))
        .Select(part => WebUtility.UrlDecode(part[1].Replace('+', ' ')) ?? string.Empty);

    private static string[] SplitCommandLine(string command)
    {
        var arguments = new List<string>();
        var current = new StringBuilder();
        char? quote = null; var started = false;
        foreach (var character in command)
        {
            if (quote is not null)
            {
                if (character == quote) quote = null;
                else current.Append(character);
                continue;
            }
            if (character is '\'' or '"') { quote = character; started = true; }
            else if (char.IsWhiteSpace(character))
            {
                if (!started) continue;
                arguments.Add(current.ToString()); current.Clear(); started = false;
            }
            else { current.Append(character); started = true; }
        }
        if (quote is not null) throw new ArgumentException("Close the quoted flag value.");
        if (started) arguments.Add(current.ToString());
        return [.. arguments];
    }

    private static async Task SendAsync(HttpListenerResponse response, string contentType, string body, HttpStatusCode status = HttpStatusCode.OK)
    {
        var bytes = Encoding.UTF8.GetBytes(body);
        response.StatusCode = (int)status;
        response.ContentType = contentType;
        response.Headers[HttpResponseHeader.CacheControl] = "no-store";
        response.ContentLength64 = bytes.Length;
        await response.OutputStream.WriteAsync(bytes);
    }

    private static Task SendJsonAsync(HttpListenerResponse response, object body) =>
        SendAsync(response, "application/json; charset=utf-8", JsonSerializer.Serialize(body));

    private static string DashboardPage()
    {
        var downloads = Downloads.OrderByDescending(entry => entry.Value.StartedAt).Take(12).ToArray();
        var cards = string.Join("", downloads.Select(entry => DownloadCard(entry.Key, entry.Value)));
        return $$"""
            <!doctype html>
            <html lang="en">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>ripmedia</title>
              <style>
                :root { color-scheme: dark; } * { box-sizing: border-box; }
                body { background: #000; color: #e0c0c6; font: 15px/1.4 ui-monospace, "Cascadia Code", Consolas, "Courier New", monospace; margin: 0; padding: 52px 16px; } #snow { height: 100%; inset: 0; pointer-events: none; position: fixed; width: 100%; } main { margin: auto; position: relative; width: min(640px, 100%); z-index: 1; }
                form { margin: 0; width: 100%; } fieldset { border: 1px solid #d6a1ac; margin: 0; min-inline-size: 0; padding: 1px 9px 4px; width: 100%; } legend { background: #d6a1ac; color: #000; font-size: .68rem; font-weight: 800; letter-spacing: .08em; padding: 2px 6px; text-transform: lowercase; }
                input { background: transparent; border: 0; color: #e0c0c6; font: inherit; outline: none; padding: 0; width: 100%; }
                .queue { display: grid; gap: 6px; margin-top: 20px; } .download { background: transparent; min-width: 0; padding: 7px 9px 7px 11px; position: relative; } .download.entering { animation: queued .42s cubic-bezier(.2,.8,.2,1) both; } @keyframes queued { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } } .download::before { background: #d6a1ac; content: ""; height: 100%; left: 0; position: absolute; top: 0; width: 2px; } .download.done::before { background: #b8ceb8; } .download.failed::before { background: #d69ba6; }
                header { align-items: baseline; display: flex; gap: 12px; min-width: 0; } .title { color: #e0c0c6; flex: 1; font-size: .78rem; margin: 0; overflow: hidden; text-overflow: ellipsis; text-decoration: none; white-space: nowrap; } .done .title { color: #a99ba0; } .title[href] { cursor: pointer; } .title[href]:hover { color: #b8ceb8; text-decoration: underline; } .meta { color: #a99ba0; display: flex; flex-shrink: 0; font-size: .68rem; gap: 8px; margin-left: auto; }
                .meter { background: #211a1d; height: 2px; margin-top: 6px; overflow: hidden; } .meter span { background: #d6a1ac; display: block; height: 100%; transition: width .65s cubic-bezier(.2,.8,.2,1); width: var(--progress, 0%); } .done .meter span { background: #b8ceb8; }
                @media (max-width: 440px) { body { padding-top: 28px; } }
              </style>
            </head>
            <body><canvas id="snow"></canvas><main><form action="/download" method="post"><fieldset><legend>ripmedia</legend><input aria-label="URL and download flags" autofocus autocomplete="off" name="url" placeholder="URL [flags]" required type="text"></fieldset></form><section class="queue">{{cards}}</section></main><script>
              const snow = document.querySelector('#snow'); const paint = snow.getContext('2d'); let flakes = []; let lastFrame = 0; let snowWidth = 0; let snowHeight = 0; let resizeTimer;
              const newFlake = () => ({ x: Math.random() * innerWidth, y: Math.random() * innerHeight, speed: 5 + Math.random() * 10, alpha: .25 + Math.random() * .6 });
              const resizeSnow = () => { const ratio = devicePixelRatio || 1; const oldWidth = snowWidth || innerWidth; const oldHeight = snowHeight || innerHeight; snowWidth = innerWidth; snowHeight = innerHeight; snow.width = snowWidth * ratio; snow.height = snowHeight * ratio; paint.setTransform(ratio, 0, 0, ratio, 0, 0); const count = Math.ceil(snowWidth * snowHeight / 15000); flakes = flakes.slice(0, count); while (flakes.length < count) flakes.push(newFlake()); for (const flake of flakes) { flake.x = Math.min(snowWidth, flake.x * snowWidth / oldWidth); flake.y = Math.min(snowHeight, flake.y * snowHeight / oldHeight); } };
              const snowFrame = time => { const elapsed = Math.min((time - lastFrame) / 1000, .1); lastFrame = time; paint.clearRect(0, 0, snowWidth, snowHeight); for (const flake of flakes) { flake.y += flake.speed * elapsed; if (flake.y > snowHeight) { flake.y = -1; flake.x = Math.random() * snowWidth; } paint.fillStyle = `rgba(255,255,255,${flake.alpha})`; paint.fillRect(Math.round(flake.x), Math.round(flake.y), 1, 1); } requestAnimationFrame(snowFrame); }; resizeSnow(); addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(resizeSnow, 120); }); requestAnimationFrame(snowFrame);
              const form = document.querySelector('form'); form.addEventListener('submit', event => { event.preventDefault(); fetch('/download', { method: 'POST', body: new URLSearchParams(new FormData(form)) }).then(() => form.reset()).catch(() => form.submit()); });
              const queue = document.querySelector('.queue');
              const text = value => document.createTextNode(value ?? '');
              const meter = (job, existing) => { const node = existing ?? document.createElement('div'); if (node.className !== 'meter') node.className = 'meter'; const fill = node.firstElementChild ?? node.appendChild(document.createElement('span')); fill.style.setProperty('--progress', `${job.progress == null ? 0 : Math.max(0, Math.min(100, Math.round(job.progress)))}%`); return node; };
              const update = (card, job) => { const snapshot = JSON.stringify(job); if (card.dataset.snapshot === snapshot) return; card.dataset.snapshot = snapshot; const classes = `download${job.done ? (job.ok ? ' done' : ' failed') : ''}${card.classList.contains('entering') ? ' entering' : ''}`; if (card.className !== classes) card.className = classes; const title = card.querySelector('.title'); title.textContent = job.title ?? ''; if (job.done && job.ok && job.paths?.length) title.href = `/open/${job.id}`; else title.removeAttribute('href'); const meta = card.querySelector('.meta'); meta.replaceChildren(...[job.progress == null ? '0%' : `${Math.max(0, Math.min(100, Math.round(job.progress)))}%`, job.speed ?? '—', job.eta ? `ETA ${job.eta}` : 'ETA —'].map(value => { const span = document.createElement('span'); span.textContent = value; return span; })); meter(job, card.querySelector('.meter')); };
              const create = job => { const card = document.createElement('article'); const header = document.createElement('header'); const title = document.createElement('a'); const meta = document.createElement('div'); const meterNode = document.createElement('div'); card.dataset.id = job.id; title.className = 'title'; meta.className = 'meta'; meterNode.className = 'meter'; meterNode.append(document.createElement('span')); header.append(title, meta); card.append(header, meterNode); update(card, job); requestAnimationFrame(() => { card.classList.add('entering'); setTimeout(() => card.classList.remove('entering'), 450); }); return card; };
              const sync = downloads => { const old = new Map([...queue.children].map(card => [card.dataset.id, card])); for (const job of downloads) { const card = old.get(job.id) ?? create(job); update(card, job); queue.append(card); old.delete(job.id); } for (const card of old.values()) card.remove(); }; const events = new EventSource('/events'); events.addEventListener('downloads', event => sync(JSON.parse(event.data).downloads));
            </script></body>
            </html>
            """;
    }

    private static string DownloadCard(string id, WebDownload download)
    {
        var percentage = download.Progress is double value ? Math.Clamp((int)Math.Round(value), 0, 100) : (int?)null;
        var transfer = new[] { $"{percentage ?? 0}%", string.IsNullOrWhiteSpace(download.Speed) ? "—" : download.Speed, string.IsNullOrWhiteSpace(download.Eta) ? "ETA —" : $"ETA {download.Eta}" }
            .Select(WebUtility.HtmlEncode);
        var meter = $"<div class=\"meter\"><span style=\"--progress:{percentage ?? 0}%\"></span></div>";
        var classes = download.Done ? (download.Ok ? "download done" : "download failed") : "download";
        var title = download.Title ?? string.Empty;
        var link = download.Done && download.Ok && download.Paths is { Count: > 0 } ? $" href=\"/open/{WebUtility.HtmlEncode(id)}\"" : string.Empty;
        return $"<article class=\"{classes}\" data-id=\"{WebUtility.HtmlEncode(id)}\"><header><a class=\"title\"{link}>{WebUtility.HtmlEncode(title)}</a><div class=\"meta\">{string.Join("", transfer.Select(item => $"<span>{item}</span>"))}</div></header>{meter}</article>";
    }

    private static void UpdateDownload(string id, Func<WebDownload, WebDownload> update)
    {
        while (Downloads.TryGetValue(id, out var current))
        {
            if (!Downloads.TryUpdate(id, update(current), current)) continue;
            _ = BroadcastDownloadsAsync();
            return;
        }
    }

    private static async Task BroadcastDownloadsAsync()
    {
        var message = $"event: downloads\ndata: {JsonSerializer.Serialize(DownloadStatusPayload())}\n\n";
        foreach (var client in EventClients)
        {
            try { await WriteEventAsync(client.Value, message); }
            catch (HttpListenerException) { EventClients.TryRemove(client.Key, out _); }
            catch (IOException) { EventClients.TryRemove(client.Key, out _); }
        }
    }

    private static async Task WriteEventAsync(StreamWriter writer, string message)
    {
        await EventWriteLock.WaitAsync();
        try { await writer.WriteAsync(message); await writer.FlushAsync(); }
        finally { EventWriteLock.Release(); }
    }

    private static string StatusPage(WebDownload download, bool refresh)
    {
        var percentage = download.Progress is double value ? Math.Clamp((int)Math.Round(value), 0, 100) : (int?)null;
        var transfer = new[] { percentage is null ? null : $"{percentage}%", download.Speed, string.IsNullOrWhiteSpace(download.Eta) ? null : $"ETA {download.Eta}" }
            .Where(value => !string.IsNullOrWhiteSpace(value)).Select(WebUtility.HtmlEncode);
        var stages = download.Stages.TakeLast(6).Select(stage =>
            $"<li class=\"{(stage.Success ? "" : "failed")}\"><b>{(stage.Success ? "✓" : "×")}</b><span>{WebUtility.HtmlEncode(stage.Name)}</span>{(string.IsNullOrWhiteSpace(stage.Detail) ? string.Empty : $"<small>{WebUtility.HtmlEncode(UiText.Truncate(stage.Detail))}</small>")}</li>");
        var paths = download.Paths is { Count: > 0 }
            ? $"<div class=\"paths\">{string.Join("<br>", download.Paths.Select(WebUtility.HtmlEncode))}</div>" : string.Empty;
        var meter = percentage is null
            ? "<div class=\"meter waiting\"><span></span></div>"
            : $"<div class=\"meter\"><span style=\"width:{percentage}%\"></span></div>";
        return $$"""
            <!doctype html>
            <html lang="en">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              {{(refresh ? "<meta http-equiv=\"refresh\" content=\"1\">" : string.Empty)}}
              <title>ripmedia</title>
              <style>
                :root { color-scheme: dark; } * { box-sizing: border-box; }
                body { align-items: center; background: #000; color: #e0c0c6; display: flex; font: 15px/1.4 ui-monospace, "Cascadia Code", Consolas, "Courier New", monospace; justify-content: center; margin: 0; min-height: 100vh; }
                main { width: min(560px, calc(100% - 32px)); } h1 { color: #d6a1ac; font-size: 1rem; font-weight: 600; letter-spacing: .08em; margin: 0 0 20px; text-transform: lowercase; }
                .state { color: {{(download.Done ? (download.Ok ? "#b8ceb8" : "#d69ba6") : "#d6a1ac")}}; font-size: 1.2rem; margin: 0; overflow-wrap: anywhere; } .meta { color: #a99ba0; display: flex; font-size: .8rem; gap: 12px; margin: 7px 0 14px; }
                .meter { background: #181315; height: 4px; overflow: hidden; } .meter span { background: #d6a1ac; display: block; height: 100%; transition: width .3s; } .meter.waiting span { animation: travel 1.4s ease-in-out infinite; width: 36%; } @keyframes travel { from { transform: translateX(-110%); } to { transform: translateX(310%); } }
                ul { border-top: 1px solid #2a2225; list-style: none; margin: 20px 0 18px; padding: 10px 0 0; } li { align-items: baseline; color: #b8ceb8; display: flex; font-size: .85rem; gap: 8px; padding: 4px 0; } li.failed { color: #d69ba6; } li b { font-weight: 600; } li small { color: #a99ba0; margin-left: auto; max-width: 58%; overflow: hidden; text-align: right; text-overflow: ellipsis; white-space: nowrap; } .paths { color: #b8ceb8; font-size: .8rem; line-height: 1.65; margin: 0 0 18px; overflow-wrap: anywhere; } a { color: #a99ba0; font-size: .85rem; }
              </style>
            </head>
            <body><main><h1>ripmedia</h1><p class="state">{{WebUtility.HtmlEncode(download.Message)}}</p><div class="meta">{{string.Join("", transfer.Select(item => $"<span>{item}</span>"))}}</div>{{meter}}<ul>{{string.Join("", stages)}}</ul>{{paths}}<a href="/">download another</a></main></body>
            </html>
            """;
    }

    private sealed record WebDownload(DateTimeOffset StartedAt, bool Done, bool Ok, string? Title, string Message, double? Progress, string? Speed, string? Eta,
        IReadOnlyList<StageResult> Stages, IReadOnlyList<string>? Paths = null);
}
