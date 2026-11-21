#if SOLOSTONE_MACOS
using System;
using System.IO;
using System.Runtime.InteropServices;
using BepInEx;
using UnityEngine;

internal static class MacPreviewRuntime
{
    private const string SystemLibrary = "/usr/lib/libSystem.B.dylib";

    [DllImport(SystemLibrary)] private static extern uint geteuid();
    [DllImport(SystemLibrary, SetLastError = true)] private static extern int socket(int domain, int type, int protocol);
    [DllImport(SystemLibrary, SetLastError = true)] private static extern int connect(int fd, byte[] address, uint length);
    [DllImport(SystemLibrary)] private static extern int close(int fd);

    internal static OfflineLaunchContext Admit(string[] args)
    {
        if (Application.platform != RuntimePlatform.OSXPlayer || geteuid() == 0)
            throw new InvalidOperationException("The macOS preview requires a regular macOS user.");

        string root = OfflineGuard.Selector(args, "-hs-macos-root", true);
        string run = OfflineGuard.Selector(args, "-hs-native-ui-run", true);
        string previous = OfflineGuard.Selector(args, "-hs-profile-previous-run", false);
        string token = OfflineGuard.Selector(args, "-hs-profile-relaunch-token", false);
        if (!Path.IsPathRooted(root) || root != Path.GetFullPath(root) || !Guid.TryParseExact(run, "D", out _)
            || (previous == null) != (token == null)
            || (previous != null && (!Guid.TryParseExact(previous, "D", out _) || !Guid.TryParseExact(token, "N", out _))))
            throw new InvalidOperationException("Malformed macOS preview launch.");

        string client = Path.Combine(root, "client");
        string gameBinaries = Path.Combine(client, "Hearthstone.app", "Contents", "MacOS");
        if (Paths.GameRootPath != client || Path.GetDirectoryName(Paths.ExecutablePath) != gameBinaries
            || Paths.BepInExRootPath != Path.Combine(client, "BepInEx"))
            throw new InvalidOperationException("The plug-in must be loaded in the SoloStone macOS copy.");

        OfflineGuard.RejectReparsePoints(Paths.ExecutablePath);
        string grant = Path.Combine(root, "reports", "macos-launch.txt");
        OfflineGuard.RejectReparsePoints(grant);
        if (!File.Exists(grant) || new FileInfo(grant).Length != run.Length || File.ReadAllText(grant) != run)
            throw new InvalidOperationException("Start this copy from the SoloStone macOS launcher.");

        RequireNetworkDenied(2, new byte[] { 16, 2, 0, 9, 127, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0 });
        RequireNetworkDenied(30, new byte[] { 28, 30, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0 });

        string version = InstallerRuntime.RuntimeCosmeticVersion();
        if (version == null || !version.StartsWith(InstallerRuntime.CompiledMajor + ".", StringComparison.Ordinal))
            throw new InvalidOperationException("This preview requires the supported Hearthstone major version.");

        string profile = Path.Combine(root, "saves", "profile.xml");
        OfflineGuard.ValidateProfileFiles(profile);
        return new OfflineLaunchContext(run, null, profile, installedRoot: root, savesPending: true,
            relaunchPreviousRunId: previous, relaunchToken: token);
    }

    private static void RequireNetworkDenied(int family, byte[] address)
    {
        // Darwin uses 1 for SOCK_STREAM and 2 for SOCK_DGRAM.
        foreach (int type in new[] { 1, 2 })
        {
            int fd = socket(family, type, 0);
            if (fd < 0)
                throw new InvalidOperationException("Could not open a socket to verify macOS network isolation.");
            try
            {
                int result = connect(fd, address, (uint)address.Length);
                int error = Marshal.GetLastWin32Error();
                // EPERM and EACCES are policy denials. Connection refused or unreachable do not prove a sandbox.
                if (result != -1 || (error != 1 && error != 13))
                    throw new InvalidOperationException("macOS network sandbox was not confirmed in the game process.");
            }
            finally { close(fd); }
        }
    }

    internal static void Confirm(OfflineLaunchContext launch)
    {
        string marker = Path.Combine(launch.Reports, "plugin-loaded.txt");
        OfflineGuard.RejectReparsePoints(marker);
        File.WriteAllText(marker, launch.RunId);
    }
}
#endif
