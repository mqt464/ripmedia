namespace Ripmedia.Core;

public static class CookieProfiles
{
    public static IReadOnlyList<BrowserCookieProfile> Discover()
    {
        if (!OperatingSystem.IsWindows()) return Array.Empty<BrowserCookieProfile>();
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var profiles = new List<BrowserCookieProfile>();
        var chromium = new[] {
            ("chrome", "Chrome", Path.Combine(local, "Google", "Chrome", "User Data")),
            ("edge", "Edge", Path.Combine(local, "Microsoft", "Edge", "User Data")),
            ("brave", "Brave", Path.Combine(local, "BraveSoftware", "Brave-Browser", "User Data")),
            ("chromium", "Chromium", Path.Combine(local, "Chromium", "User Data")) };
        foreach (var (id, name, root) in chromium)
        {
            if (!Directory.Exists(root)) continue;
            foreach (var path in Directory.EnumerateDirectories(root).Where(path => Path.GetFileName(path) == "Default" || Path.GetFileName(path).StartsWith("Profile ", StringComparison.OrdinalIgnoreCase)))
                if (File.Exists(Path.Combine(path, "Network", "Cookies")) || File.Exists(Path.Combine(path, "Cookies"))) profiles.Add(new BrowserCookieProfile(id, $"{name} · {Path.GetFileName(path)}", path));
        }
        var firefoxRoot = Path.Combine(roaming, "Mozilla", "Firefox", "Profiles");
        if (Directory.Exists(firefoxRoot)) foreach (var path in Directory.EnumerateDirectories(firefoxRoot))
            if (File.Exists(Path.Combine(path, "cookies.sqlite"))) profiles.Add(new BrowserCookieProfile("firefox", $"Firefox · {Path.GetFileName(path)}", path));
        return profiles.OrderBy(profile => profile.Browser).ThenBy(profile => profile.Profile).ToArray();
    }
}
