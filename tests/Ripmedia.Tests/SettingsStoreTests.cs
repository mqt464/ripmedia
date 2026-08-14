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
    public void Dispose() { if (Directory.Exists(_path)) Directory.Delete(_path, true); }
}
