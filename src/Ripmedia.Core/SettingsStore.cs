using System.Text.Json;

namespace Ripmedia.Core;

public sealed class SettingsStore
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };
    public string DirectoryPath { get; }
    public string SettingsPath => Path.Combine(DirectoryPath, "settings.json");

    public SettingsStore(string? directory = null) => DirectoryPath = directory ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ripmedia");

    public async Task<RipmediaSettings> LoadAsync(CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(DirectoryPath);
        if (File.Exists(SettingsPath))
        {
            await using var stream = File.OpenRead(SettingsPath);
            return await JsonSerializer.DeserializeAsync<RipmediaSettings>(stream, Options, cancellationToken) ?? new RipmediaSettings();
        }
        var settings = MigrateLegacy();
        await SaveAsync(settings, cancellationToken);
        return settings;
    }

    public async Task SaveAsync(RipmediaSettings settings, CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(DirectoryPath);
        var temporary = SettingsPath + ".tmp";
        await using (var stream = File.Create(temporary)) await JsonSerializer.SerializeAsync(stream, settings, Options, cancellationToken);
        File.Move(temporary, SettingsPath, true);
    }

    private static RipmediaSettings MigrateLegacy()
    {
        var settings = new RipmediaSettings();
        var oldPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".ripmedia", "config.ini");
        if (!File.Exists(oldPath)) return settings;
        var values = File.ReadLines(oldPath).Select(line => line.Trim()).Where(line => line.Contains('=') && !line.StartsWith('#') && !line.StartsWith(';'))
            .Select(line => line.Split('=', 2)).ToDictionary(parts => parts[0].Trim().Replace('-', '_'), parts => parts[1].Trim(), StringComparer.OrdinalIgnoreCase);
        if (values.TryGetValue("output_dir", out var output) && !string.IsNullOrWhiteSpace(output)) settings.OutputDirectory = output;
        if (values.TryGetValue("cookies", out var cookies) && !string.Equals(cookies, "none", StringComparison.OrdinalIgnoreCase)) settings.CookieFile = cookies;
        if (values.TryGetValue("no_color", out var noColor)) settings.NoColor = IsTrue(noColor);
        if (values.TryGetValue("show_file_size", out var showSize)) settings.ShowFileSize = IsTrue(showSize);
        if (values.TryGetValue("speed_unit", out var speed)) settings.SpeedUnit = speed;
        settings.MigratedLegacySettings = true;
        return settings;
    }

    private static bool IsTrue(string value) => value.Equals("true", StringComparison.OrdinalIgnoreCase) || value is "1" or "yes" or "on";
}
