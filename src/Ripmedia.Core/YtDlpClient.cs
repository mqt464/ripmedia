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
        var result = await DownloadWithFormatAsync(FormatRules.SelectSourceFormat(request.AudioOnly, request.Format));

        if (result.ExitCode != 0) throw new InvalidOperationException(CleanError(result));
        var media = Directory.EnumerateFiles(temporaryDirectory).Where(path => !path.EndsWith(".part", StringComparison.OrdinalIgnoreCase) && !IsImage(path))
            .OrderByDescending(File.GetLastWriteTimeUtc).FirstOrDefault();
        return media ?? throw new InvalidOperationException("yt-dlp finished without producing media.");

        async Task<ProcessResult> DownloadWithFormatAsync(string format)
        {
            var args = new List<string> { "--newline", "--no-warnings", "--write-thumbnail", "--output", Path.Combine(temporaryDirectory, "%(id)s.%(ext)s") };
            var toolDirectory = Path.GetDirectoryName(_executable);
            if (!string.IsNullOrWhiteSpace(toolDirectory) && File.Exists(Path.Combine(toolDirectory, "ffmpeg.exe"))) args.AddRange(["--ffmpeg-location", toolDirectory]);
            AddCookies(args, request.CookieFile, request.BrowserCookies);
            if (item.Provider == Provider.YouTube) args.AddRange(await YoutubePoTokenProvider.ArgumentsAsync(toolDirectory, request.CookieFile, request.BrowserCookies, cancellationToken));
            args.AddRange(["--format", format]);
            if (!string.IsNullOrWhiteSpace(request.Format) && FormatRules.IsAudio(request.Format)) args.AddRange(["--extract-audio", "--audio-format", request.Format]);
            else if (!string.IsNullOrWhiteSpace(request.Format)) args.AddRange(["--recode-video", request.Format]);
            args.Add(item.Url);
            return await ProcessRunner.RunAsync(_executable, args, line => progress?.Invoke(DownloadProgress.Parse(line)), cancellationToken: cancellationToken);
        }
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
        var pathEntry = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator).FirstOrDefault(directory => File.Exists(Path.Combine(directory, name)));
        if (!string.IsNullOrWhiteSpace(pathEntry)) return Path.Combine(pathEntry, name);
        throw new FileNotFoundException($"Could not find {name}. Run 'dotnet run --project src/Ripmedia.Cli' once while connected to the internet to restore the bundled tools, or install ripmedia from its release bundle.", name);
    }
}

public sealed record DownloadProgress(double? Percentage, string? Speed, string? Eta)
{
    private static readonly Regex PercentagePattern = new(@"\[download\]\s+(?<percent>[\d.]+)%", RegexOptions.Compiled);
    private static readonly Regex SpeedPattern = new(@"\bat\s+(?<speed>\S+)", RegexOptions.Compiled);
    private static readonly Regex EtaPattern = new(@"\bETA\s+(?<eta>\S+)", RegexOptions.Compiled);

    public static DownloadProgress Parse(string line)
    {
        var percentage = PercentagePattern.Match(line);
        var speed = SpeedPattern.Match(line);
        var eta = EtaPattern.Match(line);
        return new(percentage.Success ? double.Parse(percentage.Groups["percent"].Value, System.Globalization.CultureInfo.InvariantCulture) : null,
            speed.Success ? speed.Groups["speed"].Value : null, eta.Success ? eta.Groups["eta"].Value : null);
    }
}

public static class FormatRules
{
    public const string BestVideoAndAudio = "bestvideo*+bestaudio/best";
    private static readonly HashSet<string> Audio = new(StringComparer.OrdinalIgnoreCase) { "mp3", "m4a", "aac", "flac", "ogg", "opus", "wav" };
    private static readonly HashSet<string> Video = new(StringComparer.OrdinalIgnoreCase) { "mp4", "mkv", "webm" };
    public static string? Normalize(string? value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim().TrimStart('.').ToLowerInvariant();
    public static bool IsSupported(string value) => Audio.Contains(value) || Video.Contains(value);
    public static bool IsAudio(string value) => Audio.Contains(value);
    public static bool IsVideo(string value) => Video.Contains(value);
    public static string SelectSourceFormat(bool audioOnly, string? outputFormat) => audioOnly || (outputFormat is not null && IsAudio(outputFormat))
        ? "bestaudio"
        : BestVideoAndAudio;
}
