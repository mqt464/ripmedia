using Ripmedia.Core;

namespace Ripmedia.Tests;

public sealed class UrlInputTests
{
    [Fact]
    public void NormalizesTwitterStatusUrl() => Assert.Equal("https://twitter.com/i/status/123", UrlInput.Normalize("https://x.com/example/status/123?foo=bar"));

    [Fact]
    public void SanitizesWindowsReservedCharacters() => Assert.Equal("a_b", OutputPaths.Sanitize("a:b"));

    [Fact]
    public void RecognizesSupportedFormats()
    {
        Assert.True(FormatRules.IsSupported("mp3"));
        Assert.True(FormatRules.IsSupported("mkv"));
        Assert.False(FormatRules.IsSupported("exe"));
    }
}
