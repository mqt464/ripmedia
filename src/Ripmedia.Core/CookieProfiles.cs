namespace Ripmedia.Core;

public static class CookieProfiles
{
    public static IReadOnlyList<BrowserCookieProfile> Discover()
    {
        if (!OperatingSystem.IsWindows()) return Array.Empty<BrowserCookieProfile>();
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var profiles = new List<BrowserCookieProfile>();
        // yt-dlp recognises only a fixed set of browser identifiers. Chromium
        // forks such as Thorium and Helium use Chrome's cookie backend, but
        // retain their own display name in the picker.
        var chromium = new[] {
            ("chrome", "Chrome", Path.Combine(local, "Google", "Chrome", "User Data")),
            ("edge", "Edge", Path.Combine(local, "Microsoft", "Edge", "User Data")),
            ("brave", "Brave", Path.Combine(local, "BraveSoftware", "Brave-Browser", "User Data")),
            ("chromium", "Chromium", Path.Combine(local, "Chromium", "User Data")),
            ("chrome", "Thorium", Path.Combine(local, "Thorium", "User Data")),
            ("chrome", "Helium", Path.Combine(local, "imput", "Helium", "User Data")) };
        foreach (var (id, name, root) in chromium)
        {
            if (!Directory.Exists(root)) continue;
            foreach (var path in Directory.EnumerateDirectories(root).Where(path => Path.GetFileName(path) == "Default" || Path.GetFileName(path).StartsWith("Profile ", StringComparison.OrdinalIgnoreCase)))
                if (File.Exists(Path.Combine(path, "Network", "Cookies")) || File.Exists(Path.Combine(path, "Cookies"))) profiles.Add(new BrowserCookieProfile(id, Path.GetFileName(path), path, name));
        }
        var firefoxRoot = Path.Combine(roaming, "Mozilla", "Firefox", "Profiles");
        if (Directory.Exists(firefoxRoot))
            foreach (var path in Directory.EnumerateDirectories(firefoxRoot))
                if (File.Exists(Path.Combine(path, "cookies.sqlite"))) profiles.Add(new BrowserCookieProfile("firefox", Path.GetFileName(path), path, "Firefox"));
        return profiles.OrderBy(profile => profile.Browser).ThenBy(profile => profile.Profile).ToArray();
    }
}
