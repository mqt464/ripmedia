using System.Text.Json;
using System.Text.RegularExpressions;

namespace Ripmedia.Core;

public sealed class YtDlpClient
{
    private readonly string _executable;
    public YtDlpClient(string? executable = null) => _executable = executable ?? FindExecutable("yt-dlp.exe");
    public string Executable => _executable;

    public async Task<MediaItem> InspectAsync(string url, string? cookieFile, string? browserCookies, bool noPlaylist, CancellationToken cancellationToken)
    {
        var args = new List<string> { "--dump-single-json", "--skip-download", "--no-warnings" };
        AddCookies(args, cookieFile, browserCookies); if (noPlaylist) args.Add("--no-playlist"); args.Add(url);
        var result = await ProcessRunner.RunAsync(_executable, args, cancellationToken: cancellationToken);
        if (result.ExitCode != 0) throw new InvalidOperationException(CleanError(result));
        var json = result.StandardOutput.LastOrDefault(line => line.StartsWith('{')) ?? throw new InvalidOperationException("yt-dlp did not return metadata.");
        using var document = JsonDocument.Parse(json); return MediaItem.FromJson(document.RootElement, url);
    }

    public Task<ProcessResult> ListFormatsAsync(string url, string? cookieFile, string? browserCookies, CancellationToken cancellationToken)
    {
        var args = new List<string> { "--list-formats", "--no-warnings" }; AddCookies(args, cookieFile, browserCookies); args.Add(url);
        return ProcessRunner.RunAsync(_executable, args, cancellationToken: cancellationToken);
    }

    public async Task<string> DownloadAsync(MediaItem item, string temporaryDirectory, DownloadRequest request, Action<DownloadProgress>? progress, CancellationToken cancellationToken)
    {
        var args = new List<string> { "--newline", "--no-warnings", "--write-thumbnail", "--output", Path.Combine(temporaryDirectory, "%(id)s.%(ext)s") };
        var toolDirectory = Path.GetDirectoryName(_executable);
        if (!string.IsNullOrWhiteSpace(toolDirectory) && File.Exists(Path.Combine(toolDirectory, "ffmpeg.exe"))) args.AddRange(["--ffmpeg-location", toolDirectory]);
        AddCookies(args, request.CookieFile, request.BrowserCookies);
        if (request.AudioOnly && string.IsNullOrWhiteSpace(request.Format)) args.AddRange(["--format", "bestaudio"]);
        else if (string.IsNullOrWhiteSpace(request.Format)) args.AddRange(["--format", "best"]);
        else if (FormatRules.IsAudio(request.Format)) args.AddRange(["--extract-audio", "--audio-format", request.Format]);
        else args.AddRange(["--recode-video", request.Format]);
        args.Add(item.Url);
        var result = await ProcessRunner.RunAsync(_executable, args, line => progress?.Invoke(DownloadProgress.Parse(line)), cancellationToken: cancellationToken);
        if (result.ExitCode != 0) throw new InvalidOperationException(CleanError(result));
        var media = Directory.EnumerateFiles(temporaryDirectory).Where(path => !path.EndsWith(".part", StringComparison.OrdinalIgnoreCase) && !IsImage(path))
            .OrderByDescending(File.GetLastWriteTimeUtc).FirstOrDefault();
        return media ?? throw new InvalidOperationException("yt-dlp finished without producing media.");
    }

    private static void AddCookies(List<string> args, string? cookieFile, string? browserCookies)
    {
        if (!string.IsNullOrWhiteSpace(cookieFile)) args.AddRange(["--cookies", cookieFile]);
        else if (!string.IsNullOrWhiteSpace(browserCookies)) args.AddRange(["--cookies-from-browser", browserCookies]);
    }
    private static bool IsImage(string path) => Path.GetExtension(path).ToLowerInvariant() is ".jpg" or ".jpeg" or ".png" or ".webp" or ".gif" or ".bmp";
    private static string CleanError(ProcessResult result) => result.StandardError.LastOrDefault(line => !string.IsNullOrWhiteSpace(line)) ?? "yt-dlp failed.";
    private static string FindExecutable(string name)
    {
        var local = Path.Combine(AppContext.BaseDirectory, "tools", name); if (File.Exists(local)) return local;
        return name;
    }
}

public sealed record DownloadProgress(double? Percentage, string? Speed, string? Eta)
{
    private static readonly Regex Pattern = new(@"\[download\]\s+(?<percent>[\d.]+)%.*?(?:at\s+(?<speed>.+?)\s+ETA\s+(?<eta>\S+))?$", RegexOptions.Compiled);
    public static DownloadProgress Parse(string line) { var match = Pattern.Match(line); return !match.Success ? new(null, null, null) : new(double.Parse(match.Groups["percent"].Value, System.Globalization.CultureInfo.InvariantCulture), match.Groups["speed"].Success ? match.Groups["speed"].Value : null, match.Groups["eta"].Success ? match.Groups["eta"].Value : null); }
}

public static class FormatRules
{
    private static readonly HashSet<string> Audio = new(StringComparer.OrdinalIgnoreCase) { "mp3", "m4a", "aac", "flac", "ogg", "opus", "wav" };
    private static readonly HashSet<string> Video = new(StringComparer.OrdinalIgnoreCase) { "mp4", "mkv", "webm" };
    public static string? Normalize(string? value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim().TrimStart('.').ToLowerInvariant();
    public static bool IsSupported(string value) => Audio.Contains(value) || Video.Contains(value);
    public static bool IsAudio(string value) => Audio.Contains(value);
}
