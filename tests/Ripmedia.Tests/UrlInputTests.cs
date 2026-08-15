using Ripmedia.Core;
using System.Text.Json;

namespace Ripmedia.Tests;

public sealed class UrlInputTests
{
    [Fact]
    public void NormalizesTwitterStatusUrl() => Assert.Equal("https://twitter.com/i/status/123", UrlInput.Normalize("https://x.com/example/status/123?foo=bar"));

    [Fact]
    public void SanitizesWindowsReservedCharacters() => Assert.Equal("a_b", OutputPaths.Sanitize("a:b"));

    [Fact]
    public void RecognizesSupportedFormats()
    {
        Assert.True(FormatRules.IsSupported("mp3"));
        Assert.True(FormatRules.IsSupported("mkv"));
        Assert.False(FormatRules.IsSupported("exe"));
    }

    [Theory]
    [InlineData(false, null, "bestvideo*+bestaudio/best")]
    [InlineData(false, "mkv", "bestvideo*+bestaudio/best")]
    [InlineData(true, null, "bestaudio")]
    [InlineData(false, "mp3", "bestaudio")]
    public void SelectsTheHighestQualitySourceForTheOutputType(bool audioOnly, string? outputFormat, string expected)
        => Assert.Equal(expected, FormatRules.SelectSourceFormat(audioOnly, outputFormat));

    [Fact]
    public async Task StartsTheBundledYouTubeTokenProviderForASelectedBrowserProfile()
    {
        var workspace = new DirectoryInfo(AppContext.BaseDirectory);
        while (workspace is not null && !File.Exists(Path.Combine(workspace.FullName, "Ripmedia.sln"))) workspace = workspace.Parent;
        Assert.NotNull(workspace);
        var toolDirectory = Path.Combine(workspace!.FullName, "src", "Ripmedia.Cli", "tools");
        Assert.True(YoutubePoTokenProvider.IsAvailable(toolDirectory));

        var arguments = await YoutubePoTokenProvider.ArgumentsAsync(toolDirectory, null, "chrome:C:\\Users\\Test\\Chrome\\Default", CancellationToken.None);

        Assert.Contains("youtube:player_client=mweb", arguments);
        Assert.Contains(arguments, argument => argument.StartsWith("youtubepot-bgutilhttp:base_url=http://127.0.0.1:", StringComparison.Ordinal));
    }

    [Fact]
    public void AllowsNullNumericMetadata()
    {
        using var document = JsonDocument.Parse("{\"id\":\"track\",\"title\":\"Example\",\"release_year\":null,\"playlist_index\":null}");

        var item = MediaItem.FromJson(document.RootElement, "https://example.com/track");

        Assert.Null(item.Year);
        Assert.Null(item.PlaylistIndex);
    }

    [Fact]
    public void ParsesDownloadPercentageAndTransferStats()
    {
        var progress = DownloadProgress.Parse("[download]  42.7% of 10.00MiB at 2.50MiB/s ETA 00:03");

        Assert.Equal(42.7, progress.Percentage);
        Assert.Equal("2.50MiB/s", progress.Speed);
        Assert.Equal("00:03", progress.Eta);
    }

    [Fact]
    public void IgnoresFragmentDetailsInTransferStats()
    {
        var progress = DownloadProgress.Parse("[download]  42.7% of 10.00MiB at 2.50MiB/s (frag 3/12)");

        Assert.Equal("2.50MiB/s", progress.Speed);
        Assert.Null(progress.Eta);
    }

    [Theory]
    [InlineData("[Merger] Merging formats into \"example.mkv\"", "Merging streams")]
    [InlineData("[ExtractAudio] Destination: example.mp3", "Converting audio")]
    [InlineData("[VideoRemuxer] Remuxing video from webm to mp4", "Remuxing video")]
    [InlineData("[VideoConvertor] Converting video from webm to mp4", "Converting video")]
    public void DetectsFfmpegPostProcessing(string line, string activity)
    {
        var progress = DownloadProgress.Parse(line);

        Assert.True(progress.IsProcessing);
        Assert.Equal(activity, progress.Activity);
        Assert.Null(progress.Percentage);
    }

    [Fact]
    public async Task CancellingAProcessStopsItsProcessTree()
    {
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => ProcessRunner.RunAsync(
            Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
            ["/c", "ping -n 30 127.0.0.1 > nul"],
            cancellationToken: cancellation.Token));
    }
}
