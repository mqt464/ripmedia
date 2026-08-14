using System.Text.Json;

namespace Ripmedia.Core;

public enum Provider { Unknown, SoundCloud, TikTok, YouTube, Twitter }
public enum MediaKind { Track, Video, Playlist }

public sealed record MediaItem(
    string Url,
    Provider Provider,
    MediaKind Kind,
    string? Id,
    string? Title,
    string? Artist,
    string? Album,
    uint? TrackNumber,
    uint? DiscNumber,
    uint? Year,
    string? ThumbnailUrl,
    string? Extension,
    int? PlaylistIndex,
    IReadOnlyList<MediaItem>? Entries)
{
    public static MediaItem FromJson(JsonElement node, string sourceUrl)
    {
        var extractor = GetString(node, "extractor_key") ?? GetString(node, "extractor") ?? string.Empty;
        var provider = extractor.Contains("soundcloud", StringComparison.OrdinalIgnoreCase) ? Provider.SoundCloud
            : extractor.Contains("tiktok", StringComparison.OrdinalIgnoreCase) ? Provider.TikTok
            : extractor.Contains("youtube", StringComparison.OrdinalIgnoreCase) ? Provider.YouTube
            : extractor.Contains("twitter", StringComparison.OrdinalIgnoreCase) ? Provider.Twitter : Provider.Unknown;
        var playlist = string.Equals(GetString(node, "_type"), "playlist", StringComparison.OrdinalIgnoreCase)
            || extractor.Contains("YoutubeTab", StringComparison.OrdinalIgnoreCase);
        var entries = playlist && node.TryGetProperty("entries", out var rawEntries) && rawEntries.ValueKind == JsonValueKind.Array
            ? rawEntries.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.Object)
                .Select((e, i) => FromEntry(e, sourceUrl, provider, i + 1)).ToArray() : null;
        return new MediaItem(sourceUrl, provider, playlist ? MediaKind.Playlist : GuessKind(node), GetString(node, "id"),
            GetString(node, "title"), GetString(node, "artist") ?? GetString(node, "uploader") ?? GetString(node, "channel"),
            GetString(node, "album"), GetUInt(node, "track_number"), GetUInt(node, "disc_number"),
            GetUInt(node, "release_year"), GetString(node, "thumbnail"), GetString(node, "ext"), GetInt(node, "playlist_index"), entries);
    }

    private static MediaItem FromEntry(JsonElement node, string sourceUrl, Provider provider, int index) =>
        new(GetString(node, "webpage_url") ?? GetString(node, "url") ?? sourceUrl, provider, GuessKind(node), GetString(node, "id"),
            GetString(node, "title"), GetString(node, "artist") ?? GetString(node, "uploader"), GetString(node, "album"),
            GetUInt(node, "track_number"), GetUInt(node, "disc_number"), GetUInt(node, "release_year"), GetString(node, "thumbnail"),
            GetString(node, "ext"), GetInt(node, "playlist_index") ?? index, null);

    private static MediaKind GuessKind(JsonElement node) => string.Equals(GetString(node, "vcodec"), "none", StringComparison.OrdinalIgnoreCase) ? MediaKind.Track : MediaKind.Video;
    private static string? GetString(JsonElement node, string name) => node.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.String ? value.GetString() : null;
    private static uint? GetUInt(JsonElement node, string name) => node.TryGetProperty(name, out var value) && value.TryGetUInt32(out var result) ? result : null;
    private static int? GetInt(JsonElement node, string name) => node.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : null;
}

public sealed record BrowserCookieProfile(string Browser, string Profile, string Path)
{
    public string YtDlpValue => $"{Browser}:{Path}";
    public override string ToString() => $"{Browser} · {Profile}";
}

public sealed class RipmediaSettings
{
    public string OutputDirectory { get; set; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
    public string SpeedUnit { get; set; } = "MB/s";
    public bool ShowFileSize { get; set; }
    public bool NoColor { get; set; }
    public string? CookieFile { get; set; }
    public BrowserCookieProfile? BrowserCookieProfile { get; set; }
    public bool MigratedLegacySettings { get; set; }
}

public sealed record DownloadRequest(IReadOnlyList<string> Inputs, string? OutputDirectory, bool AudioOnly, string? Format,
    bool NoPlaylist, string? CookieFile, string? BrowserCookies, bool Quiet, bool Verbose, bool Debug, bool PrintPath, bool NoColor, string? SpeedUnit);
