using System.IO.Compression;
using System.Net.Http.Json;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Ripmedia.Core;

public sealed class ReleaseUpdater(HttpClient client)
{
    private const string Repository = "mqt464/ripmedia";
    public async Task<string> UpdateAsync(CancellationToken cancellationToken)
    {
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("ripmedia", "1.0"));
        var release = await client.GetFromJsonAsync<Release>("https://api.github.com/repos/" + Repository + "/releases/latest", cancellationToken) ?? throw new InvalidOperationException("No release was found.");
        var zip = release.Assets.SingleOrDefault(asset => asset.Name == "ripmedia-win-x64.zip") ?? throw new InvalidOperationException("Release has no Windows bundle.");
        var sums = release.Assets.SingleOrDefault(asset => asset.Name == "SHA256SUMS") ?? throw new InvalidOperationException("Release has no checksums.");
        var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ripmedia"); var versions = Path.Combine(root, "versions"); Directory.CreateDirectory(versions);
        var archive = Path.Combine(Path.GetTempPath(), $"ripmedia-{release.TagName}.zip"); var checksum = await client.GetStringAsync(sums.BrowserDownloadUrl, cancellationToken);
        await using (var input = await client.GetStreamAsync(zip.BrowserDownloadUrl, cancellationToken)) await using (var output = File.Create(archive)) await input.CopyToAsync(output, cancellationToken);
        var actual = Convert.ToHexString(await SHA256.HashDataAsync(File.OpenRead(archive), cancellationToken)).ToLowerInvariant();
        if (!checksum.Split('\n').Any(line => line.Trim().StartsWith(actual + "  ripmedia-win-x64.zip", StringComparison.OrdinalIgnoreCase))) throw new InvalidOperationException("Release checksum verification failed.");
        var target = Path.Combine(versions, release.TagName);
        if (!Directory.Exists(target)) ZipFile.ExtractToDirectory(archive, target);
        var bin = Path.Combine(root, "bin"); Directory.CreateDirectory(bin); await File.WriteAllTextAsync(Path.Combine(bin, "ripmedia.cmd"), "@echo off\r\n\"" + Path.Combine(target, "ripmedia.exe") + "\" %*\r\n", cancellationToken);
        File.Delete(archive); return release.TagName;
    }
    private sealed record Release(
        [property: JsonPropertyName("tag_name")] string TagName,
        [property: JsonPropertyName("assets")] List<Asset> Assets);

    private sealed record Asset(
        [property: JsonPropertyName("name")] string Name,
        [property: JsonPropertyName("browser_download_url")] string BrowserDownloadUrl);
}
