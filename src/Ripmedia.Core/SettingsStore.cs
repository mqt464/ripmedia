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
        var settings = new RipmediaSettings();
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

}
