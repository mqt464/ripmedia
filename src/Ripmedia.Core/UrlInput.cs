using System.Text.RegularExpressions;

namespace Ripmedia.Core;

public static partial class UrlInput
{
    public static IReadOnlyList<string> Expand(IEnumerable<string> inputs)
    {
        var result = new List<string>();
        foreach (var input in inputs)
        {
            if (File.Exists(input))
                result.AddRange(File.ReadLines(input).Select(line => line.Trim()).Where(line => line.Length > 0 && !line.StartsWith('#')));
            else if (!string.IsNullOrWhiteSpace(input)) result.Add(input.Trim());
        }
        return result.Select(Normalize).ToArray();
    }

    public static string Normalize(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)) return url;
        var host = uri.Host.ToLowerInvariant();
        if (host is "twitter.com" or "www.twitter.com" or "mobile.twitter.com" or "x.com" or "www.x.com" or "mobile.x.com")
        {
            var match = StatusId().Match(uri.AbsolutePath);
            return match.Success ? $"https://twitter.com/i/status/{match.Groups[1].Value}" : $"https://twitter.com{uri.AbsolutePath}";
        }
        return url;
    }

    [GeneratedRegex(@"/(?:i/)?status/(\d+)", RegexOptions.IgnoreCase)]
    private static partial Regex StatusId();
}
