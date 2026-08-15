using System.Diagnostics;
using System.Net;
using System.Net.Sockets;

namespace Ripmedia.Core;

public static class YoutubePoTokenProvider
{
    private static readonly SemaphoreSlim Gate = new(1, 1);
    private static Process? _process;
    private static int _port;

    static YoutubePoTokenProvider() => AppDomain.CurrentDomain.ProcessExit += (_, _) => Stop();

    public static async Task<IReadOnlyList<string>> ArgumentsAsync(string? toolDirectory, string? cookieFile, string? browserCookies, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(cookieFile) && string.IsNullOrWhiteSpace(browserCookies)) return [];
        if (!TryGetResources(toolDirectory, out var resources)) throw new InvalidOperationException("YouTube high-quality support is unavailable because the bundled PO-token provider is missing. Install a current ripmedia release.");

        var port = await EnsureRunningAsync(resources, cancellationToken);
        return [
            "--plugin-dirs", resources.PluginDirectory,
            "--js-runtimes", $"node:{resources.Node}",
            "--extractor-args", "youtube:player_client=mweb",
            "--extractor-args", $"youtubepot-bgutilhttp:base_url=http://127.0.0.1:{port}"
        ];
    }

    public static bool IsAvailable(string? toolDirectory) => TryGetResources(toolDirectory, out _);

    private static bool TryGetResources(string? toolDirectory, out Resources resources)
    {
        resources = default;
        if (string.IsNullOrWhiteSpace(toolDirectory)) return false;
        var providerDirectory = Path.Combine(toolDirectory, "pot-provider");
        var node = Path.Combine(providerDirectory, "node.exe");
        var entryPoint = Path.Combine(providerDirectory, "server", "build", "main.js");
        var pluginDirectory = Path.Combine(toolDirectory, "yt-dlp-plugins");
        var plugin = Path.Combine(pluginDirectory, "bgutil-ytdlp-pot-provider.zip");
        if (!File.Exists(node) || !File.Exists(entryPoint) || !File.Exists(plugin)) return false;
        resources = new(node, entryPoint, pluginDirectory);
        return true;
    }

    private static async Task<int> EnsureRunningAsync(Resources resources, CancellationToken cancellationToken)
    {
        await Gate.WaitAsync(cancellationToken);
        try
        {
            if (_process is { HasExited: false }) return _port;
            Stop();
            _port = ReservePort();
            var start = new ProcessStartInfo(resources.Node) { UseShellExecute = false, CreateNoWindow = true };
            start.ArgumentList.Add(resources.EntryPoint);
            start.ArgumentList.Add("--port");
            start.ArgumentList.Add(_port.ToString(System.Globalization.CultureInfo.InvariantCulture));
            _process = Process.Start(start) ?? throw new InvalidOperationException("Could not start the bundled YouTube PO-token provider.");
            try
            {
                await WaitForPortAsync(_port, _process, cancellationToken);
                return _port;
            }
            catch { Stop(); throw; }
        }
        finally { Gate.Release(); }
    }

    private static int ReservePort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    private static async Task WaitForPortAsync(int port, Process process, CancellationToken cancellationToken)
    {
        var deadline = DateTime.UtcNow.AddSeconds(20);
        while (DateTime.UtcNow < deadline)
        {
            if (process.HasExited) throw new InvalidOperationException("The bundled YouTube PO-token provider stopped before it was ready.");
            try
            {
                using var client = new TcpClient();
                await client.ConnectAsync(IPAddress.Loopback, port, cancellationToken);
                return;
            }
            catch (SocketException) { await Task.Delay(100, cancellationToken); }
        }
        throw new TimeoutException("The bundled YouTube PO-token provider did not start in time.");
    }

    private static void Stop()
    {
        try
        {
            if (_process is { HasExited: false }) _process.Kill(true);
            _process?.Dispose();
        }
        catch (InvalidOperationException) { }
        finally
        {
            _process = null;
            _port = 0;
        }
    }

    private readonly record struct Resources(string Node, string EntryPoint, string PluginDirectory);
}
