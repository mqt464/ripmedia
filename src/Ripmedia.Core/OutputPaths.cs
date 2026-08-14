using System.Text.RegularExpressions;

namespace Ripmedia.Core;

public static partial class OutputPaths
{
    public static string Sanitize(string? value)
    {
        var text = Invalid().Replace((value ?? "unknown").Trim(), "_");
        text = Control().Replace(text, "_");
        text = Whitespace().Replace(text, " ").Trim().TrimEnd('.', ' ');
        return string.IsNullOrWhiteSpace(text) ? "unknown" : text;
    }

    public static string CreatePath(MediaItem item, string outputDirectory, string extension, bool collection)
    {
        var folder = collection ? Path.Combine(outputDirectory, Sanitize(item.Album ?? item.Title)) : outputDirectory;
        var name = item.Kind == MediaKind.Track && !string.IsNullOrWhiteSpace(item.Artist) ? $"{Sanitize(item.Artist)} - {Sanitize(item.Title)}" : Sanitize(item.Title);
        if (collection && item.PlaylistIndex is int index) name = $"{index:D2} - {Sanitize(item.Title)}";
        return Unique(Path.Combine(folder, name + "." + extension.TrimStart('.')));
    }

    public static string Unique(string path)
    {
        if (!File.Exists(path)) return path;
        var dir = Path.GetDirectoryName(path) ?? "."; var stem = Path.GetFileNameWithoutExtension(path); var ext = Path.GetExtension(path);
        for (var i = 1; i < 10000; i++) { var candidate = Path.Combine(dir, $"{stem} ({i}){ext}"); if (!File.Exists(candidate)) return candidate; }
        throw new IOException("Could not select a unique output name.");
    }

    [GeneratedRegex("[<>:\"/\\\\|?*]")] private static partial Regex Invalid();
    [GeneratedRegex("[\\x00-\\x1f]")] private static partial Regex Control();
    [GeneratedRegex("\\s+")] private static partial Regex Whitespace();
}
