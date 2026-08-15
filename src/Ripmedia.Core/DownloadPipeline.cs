namespace Ripmedia.Core;

public sealed record StageResult(string Name, bool Success, string? Detail = null);
public sealed record DownloadResult(IReadOnlyList<string> Paths, IReadOnlyList<StageResult> Stages);

public sealed class DownloadPipeline(YtDlpClient ytDlp, MediaTagger tagger)
{
    public async Task<DownloadResult> RunAsync(DownloadRequest request, RipmediaSettings settings, Action<StageResult>? stage, Action<DownloadProgress>? progress, CancellationToken cancellationToken)
    {
        var allPaths = new List<string>(); var allStages = new List<StageResult>();
        var effectiveRequest = request with
        {
            CookieFile = request.CookieFile ?? settings.CookieFile,
            BrowserCookies = request.BrowserCookies ?? settings.BrowserCookieProfile?.YtDlpValue
        };
        var requestedFormat = FormatRules.Normalize(request.Format);
        ValidateFormat(requestedFormat, "Requested");
        var defaultAudioFormat = FormatRules.Normalize(settings.DefaultAudioFormat);
        var defaultVideoFormat = FormatRules.Normalize(settings.DefaultVideoFormat);
        var urls = UrlInput.Expand(request.Inputs); if (urls.Count == 0) throw new ArgumentException("Supply at least one URL or URL file.");
        foreach (var url in urls)
        {
            MediaItem root;
            try { root = await ytDlp.InspectAsync(url, effectiveRequest.CookieFile, effectiveRequest.BrowserCookies, effectiveRequest.NoPlaylist, cancellationToken); }
            catch (Exception exception) { Add("Inspect", false, exception.Message); continue; }
            Add("Inspect", true, root.Title ?? root.Url);
            var entries = root.Kind == MediaKind.Playlist && !request.NoPlaylist && root.Entries is { Count: > 0 } ? root.Entries : [root];
            foreach (var item in entries)
            {
                var useAudioFormat = request.AudioOnly || item.Kind == MediaKind.Track;
                var format = requestedFormat ?? (useAudioFormat ? defaultAudioFormat : defaultVideoFormat);
                if (requestedFormat is null) ValidateDefaultFormat(format, useAudioFormat ? "DefaultAudioFormat" : "DefaultVideoFormat", useAudioFormat ? "audio" : "video", useAudioFormat ? FormatRules.IsAudio : FormatRules.IsVideo);
                var temp = Path.Combine(Path.GetTempPath(), "ripmedia", Guid.NewGuid().ToString("N")); Directory.CreateDirectory(temp);
                try
                {
                    Add("Download", true, item.Title ?? item.Url);
                    var media = await ytDlp.DownloadAsync(item, temp, effectiveRequest with { Format = format }, progress, cancellationToken);
                    if (format is not null) Add("Convert", true, format);
                    var tagged = await tagger.TagAsync(media, item, temp, cancellationToken); Add("Tag", true, tagged ? null : "skipped");
                    var output = request.OutputDirectory ?? settings.OutputDirectory;
                    var target = OutputPaths.CreatePath(item, output, Path.GetExtension(media).TrimStart('.'), root.Kind == MediaKind.Playlist);
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!); File.Move(media, target); allPaths.Add(target); Add("Saved", true, target);
                }
                catch (Exception exception) { Add("Download", false, exception.Message); }
                finally
                {
                    try { Directory.Delete(temp, true); }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                }
            }
        }
        return new DownloadResult(allPaths, allStages);
        void Add(string name, bool success, string? detail = null) { var result = new StageResult(name, success, detail); allStages.Add(result); stage?.Invoke(result); }
    }

    private static void ValidateFormat(string? format, string description)
    {
        if (format is not null && !FormatRules.IsSupported(format)) throw new ArgumentException($"{description} format '{format}' is unsupported.");
    }

    private static void ValidateDefaultFormat(string? format, string setting, string expectedType, Func<string, bool> isExpectedType)
    {
        ValidateFormat(format, setting);
        if (format is not null && !isExpectedType(format)) throw new ArgumentException($"{setting} must be a {expectedType} format.");
    }
}
