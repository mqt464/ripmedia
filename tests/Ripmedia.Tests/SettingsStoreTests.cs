using Ripmedia.Core;

namespace Ripmedia.Tests;

public sealed class SettingsStoreTests : IDisposable
{
    private readonly string _path = Path.Combine(Path.GetTempPath(), "ripmedia-tests", Guid.NewGuid().ToString("N"));
    [Fact]
    public async Task PersistsSettingsAtomically()
    {
        var store = new SettingsStore(_path); var settings = await store.LoadAsync(); settings.OutputDirectory = "C:\\Media"; await store.SaveAsync(settings);
        Assert.Equal("C:\\Media", (await store.LoadAsync()).OutputDirectory);
    }
    [Fact]
    public async Task CreatesBlankDefaultConversionFormats()
    {
        var settings = await new SettingsStore(_path).LoadAsync();
        Assert.Equal(string.Empty, settings.DefaultAudioFormat);
        Assert.Equal(string.Empty, settings.DefaultVideoFormat);
    }
    [Fact]
    public void DisplaysForkNameButUsesChromeForYtDlp()
    {
        var profile = new BrowserCookieProfile("chrome", "Default", "C:\\Users\\Test\\AppData\\Local\\Thorium\\User Data\\Default", "Thorium");

        Assert.Equal("Thorium · Default", profile.ToString());
        Assert.StartsWith("chrome:", profile.YtDlpValue);
    }
    public void Dispose() { if (Directory.Exists(_path)) Directory.Delete(_path, true); }
}
