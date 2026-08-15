using System.Diagnostics;

var directory = AppContext.BaseDirectory;
var manifest = Path.Combine(directory, "current.txt");
if (!File.Exists(manifest))
{
    Console.Error.WriteLine("ripmedia is not installed correctly. Run the installer again.");
    return 1;
}

var target = (await File.ReadAllTextAsync(manifest)).Trim();
if (!Path.IsPathFullyQualified(target) || !File.Exists(target))
{
    Console.Error.WriteLine("The installed ripmedia version is unavailable. Run the installer again.");
    return 1;
}

var start = new ProcessStartInfo(target) { UseShellExecute = false };
foreach (var argument in args) start.ArgumentList.Add(argument);

using var process = Process.Start(start) ?? throw new InvalidOperationException("Could not start ripmedia.");
await process.WaitForExitAsync();
return process.ExitCode;
