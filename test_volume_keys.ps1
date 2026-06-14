Add-Type @'
using System;
using System.Runtime.InteropServices;
public class VolKeys {
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);
    public const byte VK_VOLUME_DOWN = 0xAE;
    public const byte VK_VOLUME_UP = 0xAF;
    public const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public static void Down(int n) {
        for (int i = 0; i < n; i++) {
            keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_EXTENDEDKEY, 0);
            keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0);
            System.Threading.Thread.Sleep(15);
        }
    }
}
'@
Write-Output "before test"
[VolKeys]::Down(2)
Write-Output "done"
