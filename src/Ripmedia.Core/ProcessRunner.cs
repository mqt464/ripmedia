using System.Diagnostics;

namespace Ripmedia.Core;

public sealed record ProcessResult(int ExitCode, IReadOnlyList<string> StandardOutput, IReadOnlyList<string> StandardError);

public static class ProcessRunner
{
    public static async Task<ProcessResult> RunAsync(string executable, IEnumerable<string> arguments, Action<string>? stdout = null, Action<string>? stderr = null, CancellationToken cancellationToken = default)
    {
        var start = new ProcessStartInfo(executable) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = start };
        var output = new List<string>(); var errors = new List<string>();
        process.Start();
        var outTask = ReadAsync(process.StandardOutput, output, stdout); var errTask = ReadAsync(process.StandardError, errors, stderr);
        try { await process.WaitForExitAsync(cancellationToken); }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            try { if (!process.HasExited) process.Kill(true); }
            catch (InvalidOperationException) { }
            await Task.WhenAll(outTask, errTask);
            throw;
        }
        await Task.WhenAll(outTask, errTask);
        return new ProcessResult(process.ExitCode, output, errors);
    }

    private static async Task ReadAsync(StreamReader reader, List<string> sink, Action<string>? callback)
    {
        while (await reader.ReadLineAsync() is { } line) { sink.Add(line); callback?.Invoke(line); }
    }
}
