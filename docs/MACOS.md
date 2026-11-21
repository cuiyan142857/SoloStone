# SoloStone macOS preview

The command-line preview builds from your own macOS copy of Hearthstone and uses the game's interface. The first
target is Hearthstone major version 37, with Unity 6000.3.11 and the Mono scripting backend. BepInEx and Harmony
compatibility still needs a live check on your Mac, including whether your Hearthstone executable runs as arm64 or
x86_64. The preview requires Python 3.10 or later, the .NET SDK in [global.json](../global.json), and enough disk
space for a separate client copy. A refresh temporarily needs space for a second copy.

From a checkout of the preview branch, run these commands. Replace the game path with yours.

```sh
python3 installer/macos_preview.py check
python3 installer/macos_preview.py prepare "/Applications/Hearthstone/Hearthstone.app"
python3 installer/macos_preview.py launch
```

- **Check** exercises the macOS Seatbelt policy with IPv4 and IPv6 TCP and UDP connections and a write outside the
  preview directory.
- **Prepare** reads your Hearthstone bundle and its separate game data when present. It copies them into
  `~/Library/Application Support/SoloStone macOS Preview`, downloads the hash-pinned macOS BepInEx package and Unity
  Mono libraries, and builds the SoloStone plugin against the copied client. The client and its assemblies stay on your Mac.
- **Launch** verifies the staged files and starts the copy inside the same Seatbelt policy. The plugin checks the
  network policy again inside the game and runs its normal client checks before opening a save. Keep the terminal
  open while playing. Start the preview with this command each time, since opening the copied app in Finder starts
  it outside the preview sandbox.

After pulling a preview update, repeat `prepare` with the original installation path, then run `launch`. The preview
keeps its saves under `saves` and retains one previous game copy. The Windows installer and signed update channel
remain separate from this preview.

For a first live check, open the collection, start an offline match and finish it, then quit and reopen the preview
to check that the result persisted. If launch stops before confirming, inspect `reports/Unity.log`,
`reports/client-check.txt` and `client/BepInEx/LogOutput.log` inside the preview directory. The logs can contain local
paths or a user name. For a Mono assembly load failure, `prepare --stock-mono <client>` can help determine whether
the pinned unstripped libraries were involved. A launch blocked by macOS code signing or library validation needs
a compatible client and loader combination.
