using System.Net.Http;
using TagLib;

namespace Ripmedia.Core;

public sealed class MediaTagger(HttpClient httpClient)
{
    public async Task<bool> TagAsync(string path, MediaItem item, string temporaryDirectory, CancellationToken cancellationToken)
    {
        if (Path.GetExtension(path).ToLowerInvariant() is not (".mp3" or ".m4a" or ".mp4" or ".flac" or ".ogg")) return false;
        try
        {
            using var file = TagLib.File.Create(path);
            file.Tag.Title = item.Title;
            file.Tag.Performers = string.IsNullOrWhiteSpace(item.Artist) ? [] : [item.Artist];
            file.Tag.Album = item.Album;
            file.Tag.Track = item.TrackNumber ?? 0;
            file.Tag.Disc = item.DiscNumber ?? 0;
            file.Tag.Year = item.Year ?? 0;
            var artwork = Directory.EnumerateFiles(temporaryDirectory).FirstOrDefault(fileName => Path.GetExtension(fileName).ToLowerInvariant() is ".jpg" or ".jpeg" or ".png" or ".webp");
            if (artwork is null && Uri.TryCreate(item.ThumbnailUrl, UriKind.Absolute, out var artworkUri))
            {
                var bytes = await httpClient.GetByteArrayAsync(artworkUri, cancellationToken);
                artwork = Path.Combine(temporaryDirectory, "artwork.jpg"); await System.IO.File.WriteAllBytesAsync(artwork, bytes, cancellationToken);
            }
            if (artwork is not null && System.IO.File.Exists(artwork)) file.Tag.Pictures = [new Picture(artwork) { Type = PictureType.FrontCover, Description = "Cover" }];
            file.Save();
            return true;
        }
        catch (Exception error) when (error is CorruptFileException or UnsupportedFormatException or HttpRequestException or IOException or UnauthorizedAccessException) { return false; }
    }
}
