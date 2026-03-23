"""OS-specific device enumeration (monitors and microphones).

All functions return a list of (display_name, value) tuples where *value* is
what gets written into the OBS source settings dict for the relevant property.
"""

import re
import subprocess


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def _enum_monitors_win32() -> list[tuple[str, str]]:
    """Return [(display_name, gdi_device_name), ...] for each monitor via Win32.

    The value is the GDI device name (e.g. "\\\\.\\DISPLAY1") which is what
    OBS's screen_capture_kit source expects for its "monitor_id" property.
    """
    import ctypes
    import ctypes.wintypes as wt

    monitors: list[tuple[str, str]] = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM,
    )

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize",    wt.DWORD),
            ("rcMonitor", wt.RECT),
            ("rcWork",    wt.RECT),
            ("dwFlags",   wt.DWORD),
            ("szDevice",  ctypes.c_wchar * 32),
        ]

    MONITORINFOF_PRIMARY = 0x00000001

    def _callback(hmon, _hdc, _lprect, _lparam):
        mi = MONITORINFOEX()
        mi.cbSize = ctypes.sizeof(MONITORINFOEX)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        w = r.right - r.left
        h = r.bottom - r.top
        idx = len(monitors)
        label = f"Monitor {idx + 1}: {w}×{h} @ {r.left},{r.top}"
        if mi.dwFlags & MONITORINFOF_PRIMARY:
            label += " (primary)"
        # szDevice is the GDI device name, e.g. "\\.\DISPLAY1"
        monitors.append((label, mi.szDevice))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(
        None, None, MONITORENUMPROC(_callback), 0,
    )
    return monitors


def _enum_mics_win32() -> list[tuple[str, str]]:
    """Return [(friendly_name, wasapi_device_id), ...] via Win32 MMDevice API."""
    import ctypes
    import ctypes.wintypes as wt

    ole32 = ctypes.windll.ole32

    # --- COM GUIDs ---
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wt.DWORD),
            ("Data2", wt.WORD),
            ("Data3", wt.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def _make_guid(s: str) -> GUID:
        import uuid
        u = uuid.UUID(s)
        b = u.bytes_le
        g = GUID()
        g.Data1 = int.from_bytes(b[0:4], "little")
        g.Data2 = int.from_bytes(b[4:6], "little")
        g.Data3 = int.from_bytes(b[6:8], "little")
        for i in range(8):
            g.Data4[i] = b[8 + i]
        return g

    IID_IMMDeviceEnumerator = _make_guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
    CLSID_MMDeviceEnumerator = _make_guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
    IID_IPropertyStore     = _make_guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")

    PKEY_Device_FriendlyName_fmtid = _make_guid("a45c254e-df1c-4efd-8020-67d146a850e0")
    PKEY_Device_FriendlyName_pid   = 14

    eCapture   = 1
    DEVICE_STATE_ACTIVE = 0x00000001

    STGM_READ = 0x00000000

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wt.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort),
                    ("pad1", ctypes.c_ushort),
                    ("pad2", ctypes.c_ushort),
                    ("pad3", ctypes.c_ushort),
                    ("data", ctypes.c_uint64)]

    ole32.CoInitialize(None)
    try:
        # Create IMMDeviceEnumerator
        enumerator = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_MMDeviceEnumerator),
            None,
            1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(IID_IMMDeviceEnumerator),
            ctypes.byref(enumerator),
        )
        if hr != 0:
            return []

        # IMMDeviceEnumerator vtable layout (offset from IUnknown):
        # QueryInterface=0, AddRef=1, Release=2,
        # EnumAudioEndpoints=3, GetDefaultAudioEndpoint=4, GetDevice=5,
        # RegisterNotificationClient=6, UnregisterNotificationClient=7
        vtbl = ctypes.cast(enumerator, ctypes.POINTER(ctypes.c_void_p))
        vtbl = ctypes.cast(vtbl[0], ctypes.POINTER(ctypes.c_void_p))

        # EnumAudioEndpoints(dataFlow, dwStateMask, ppDevices)
        EnumAudioEndpoints = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )(vtbl[3])

        collection = ctypes.c_void_p()
        hr = EnumAudioEndpoints(enumerator, eCapture, DEVICE_STATE_ACTIVE,
                                ctypes.byref(collection))
        if hr != 0:
            return []

        # IMMDeviceCollection vtable: QI=0, AddRef=1, Release=2, GetCount=3, Item=4
        coll_vtbl = ctypes.cast(collection, ctypes.POINTER(ctypes.c_void_p))
        coll_vtbl = ctypes.cast(coll_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

        GetCount = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
        )(coll_vtbl[3])
        Item = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )(coll_vtbl[4])

        count = ctypes.c_uint()
        GetCount(collection, ctypes.byref(count))

        results: list[tuple[str, str]] = []
        for i in range(count.value):
            device = ctypes.c_void_p()
            if Item(collection, i, ctypes.byref(device)) != 0:
                continue

            # IMMDevice vtable: QI=0, AddRef=1, Release=2,
            # Activate=3, OpenPropertyStore=4, GetId=5, GetState=6
            dev_vtbl = ctypes.cast(device, ctypes.POINTER(ctypes.c_void_p))
            dev_vtbl = ctypes.cast(dev_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

            # GetId → LPWSTR (caller must CoTaskMemFree)
            GetId = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_wchar_p),
            )(dev_vtbl[5])
            dev_id = ctypes.c_wchar_p()
            if GetId(device, ctypes.byref(dev_id)) != 0:
                continue
            device_id_str = dev_id.value or ""
            ole32.CoTaskMemFree(dev_id)

            # OpenPropertyStore(STGM_READ, &store)
            OpenPropertyStore = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, wt.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            )(dev_vtbl[4])
            store = ctypes.c_void_p()
            if OpenPropertyStore(device, STGM_READ, ctypes.byref(store)) != 0:
                results.append((device_id_str, device_id_str))
                continue

            # IPropertyStore vtable: QI=0, AddRef=1, Release=2,
            # GetCount=3, GetAt=4, GetValue=5, SetValue=6, Commit=7
            ps_vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))
            ps_vtbl = ctypes.cast(ps_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

            GetValue = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p,
                ctypes.POINTER(PROPERTYKEY),
                ctypes.POINTER(PROPVARIANT),
            )(ps_vtbl[5])

            pk = PROPERTYKEY()
            pk.fmtid = PKEY_Device_FriendlyName_fmtid
            pk.pid   = PKEY_Device_FriendlyName_pid

            pv = PROPVARIANT()
            friendly = device_id_str
            if GetValue(store, ctypes.byref(pk), ctypes.byref(pv)) == 0:
                # vt==31 (VT_LPWSTR) → data holds a pointer to wchar_t string
                if pv.vt == 31:
                    ptr = ctypes.cast(pv.data, ctypes.c_wchar_p)
                    friendly = ptr.value or device_id_str
                    # PropVariantClear to free the string
                    try:
                        ole32.PropVariantClear(ctypes.byref(pv))
                    except Exception:
                        pass

            # IPropertyStore::Release
            Release_ps = ctypes.WINFUNCTYPE(
                ctypes.c_ulong, ctypes.c_void_p,
            )(ps_vtbl[2])
            Release_ps(store)

            results.append((friendly, device_id_str))

        return results
    finally:
        ole32.CoUninitialize()


def _enum_webcams_win32() -> list[tuple[str, str]]:
    """Return [(friendly_name, dshow_device_id), ...] via DirectShow ICreateDevEnum.

    The value is the DirectShow device path string that OBS's dshow_input source
    expects for its "video_device_id" property.
    """
    import ctypes
    import ctypes.wintypes as wt

    ole32 = ctypes.windll.ole32

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wt.DWORD),
            ("Data2", wt.WORD),
            ("Data3", wt.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def _make_guid(s: str) -> GUID:
        import uuid
        u = uuid.UUID(s)
        b = u.bytes_le
        g = GUID()
        g.Data1 = int.from_bytes(b[0:4], "little")
        g.Data2 = int.from_bytes(b[4:6], "little")
        g.Data3 = int.from_bytes(b[6:8], "little")
        for i in range(8):
            g.Data4[i] = b[8 + i]
        return g

    CLSID_SystemDeviceEnum       = _make_guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")
    IID_ICreateDevEnum           = _make_guid("29840822-5B84-11D0-BD3B-00A0C911CE86")
    CLSID_VideoInputDeviceCategory = _make_guid("860BB310-5D01-11D0-BD3B-00A0C911CE86")
    IID_IEnumMoniker             = _make_guid("00000102-0000-0000-C000-000000000046")
    IID_IPropertyBag             = _make_guid("55272A00-42CB-11CE-8135-00AA004BB851")

    ole32.CoInitialize(None)
    try:
        # CoCreateInstance(CLSID_SystemDeviceEnum) → ICreateDevEnum
        dev_enum = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_SystemDeviceEnum),
            None, 1,
            ctypes.byref(IID_ICreateDevEnum),
            ctypes.byref(dev_enum),
        )
        if hr != 0:
            return []

        # ICreateDevEnum vtable: QI=0, AddRef=1, Release=2, CreateClassEnumerator=3
        cde_vtbl = ctypes.cast(dev_enum, ctypes.POINTER(ctypes.c_void_p))
        cde_vtbl = ctypes.cast(cde_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

        CreateClassEnumerator = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
            wt.DWORD,
        )(cde_vtbl[3])

        enum_moniker = ctypes.c_void_p()
        hr = CreateClassEnumerator(
            dev_enum,
            ctypes.byref(CLSID_VideoInputDeviceCategory),
            ctypes.byref(enum_moniker),
            0,
        )
        # S_FALSE (1) means the category is empty
        if hr != 0 or not enum_moniker:
            return []

        # IEnumMoniker vtable: QI=0, AddRef=1, Release=2, Next=3, Skip=4, Reset=5, Clone=6
        em_vtbl = ctypes.cast(enum_moniker, ctypes.POINTER(ctypes.c_void_p))
        em_vtbl = ctypes.cast(em_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

        Next = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        )(em_vtbl[3])

        results: list[tuple[str, str]] = []
        while True:
            moniker = ctypes.c_void_p()
            fetched = ctypes.c_ulong(0)
            hr = Next(enum_moniker, 1, ctypes.byref(moniker), ctypes.byref(fetched))
            if hr != 0 or fetched.value == 0:
                break

            # IMoniker vtable inherits IUnknown(0-2) + IPersist(3) +
            # IPersistStream(4-7) + IMoniker: BindToObject=8, BindToStorage=9
            mon_vtbl = ctypes.cast(moniker, ctypes.POINTER(ctypes.c_void_p))
            mon_vtbl = ctypes.cast(mon_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

            BindToStorage = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )(mon_vtbl[9])

            prop_bag = ctypes.c_void_p()
            hr = BindToStorage(
                moniker, None, None,
                ctypes.byref(IID_IPropertyBag),
                ctypes.byref(prop_bag),
            )
            if hr != 0 or not prop_bag:
                continue

            # IPropertyBag vtable: QI=0, AddRef=1, Release=2, Read=3, Write=4
            pb_vtbl = ctypes.cast(prop_bag, ctypes.POINTER(ctypes.c_void_p))
            pb_vtbl = ctypes.cast(pb_vtbl[0], ctypes.POINTER(ctypes.c_void_p))

            # VARIANT for string (VT_BSTR = 8)
            class VARIANT(ctypes.Structure):
                _fields_ = [
                    ("vt",   ctypes.c_ushort),
                    ("pad1", ctypes.c_ushort),
                    ("pad2", ctypes.c_ushort),
                    ("pad3", ctypes.c_ushort),
                    ("data", ctypes.c_void_p),
                ]

            Read = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.POINTER(VARIANT),
                ctypes.c_void_p,
            )(pb_vtbl[3])

            def _read_prop(name: str) -> str:
                v = VARIANT()
                v.vt = 0  # VT_EMPTY
                if Read(prop_bag, name, ctypes.byref(v), None) == 0 and v.vt == 8:
                    # VT_BSTR: data is a BSTR (length-prefixed wchar_t*)
                    val = ctypes.wstring_at(v.data) if v.data else ""
                    # SysFreeString
                    try:
                        ctypes.windll.oleaut32.SysFreeString(v.data)
                    except Exception:
                        pass
                    return val
                return ""

            friendly = _read_prop("FriendlyName")
            dev_path = _read_prop("DevicePath")
            if friendly:
                results.append((friendly, dev_path or friendly))

            # IPropertyBag::Release
            Release_pb = ctypes.WINFUNCTYPE(
                ctypes.c_ulong, ctypes.c_void_p,
            )(pb_vtbl[2])
            Release_pb(prop_bag)

        return results
    finally:
        ole32.CoUninitialize()

# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

def _enum_monitors_linux() -> list[tuple[str, str]]:
    """Return monitor list on Linux using xrandr output."""
    try:
        out = subprocess.check_output(
            ["xrandr", "--listmonitors"], text=True, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    results = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+):\s+[+*]?(\S+)\s+(\d+)/\d+x(\d+)/\d+\+\d+\+\d+", line)
        if m:
            idx, name, w, h = m.group(1), m.group(2), m.group(3), m.group(4)
            results.append((f"{name} ({w}×{h})", idx))
    return results


def _enum_mics_linux() -> list[tuple[str, str]]:
    """Return microphone list on Linux using pactl."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    results = []
    current_name = current_desc = None
    for line in out.splitlines():
        m = re.match(r"\s*Name:\s+(\S+)", line)
        if m:
            current_name = m.group(1)
            current_desc = None
        m2 = re.match(r"\s*Description:\s+(.+)", line)
        if m2:
            current_desc = m2.group(1).strip()
        if current_name and current_desc:
            if "monitor" not in current_name.lower():
                results.append((current_desc, current_name))
            current_name = current_desc = None
    return results


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

def _enum_monitors_darwin() -> list[tuple[str, str]]:
    """Return monitor list on macOS using system_profiler."""
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType"], text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    results = []
    idx = 0
    for line in out.splitlines():
        m = re.match(r"\s+Resolution:\s+(\d+)\s*x\s*(\d+)", line)
        if m:
            results.append((f"Display {idx + 1}: {m.group(1)}×{m.group(2)}", str(idx)))
            idx += 1
    return results


def _enum_mics_darwin() -> list[tuple[str, str]]:
    """Return microphone list on macOS using system_profiler."""
    try:
        out = subprocess.check_output(
            ["system_profiler", "SPAudioDataType"], text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    results = []
    in_input = False
    for line in out.splitlines():
        if "Input" in line and ":" in line:
            in_input = True
        elif in_input and line.strip().endswith(":"):
            name = line.strip().rstrip(":")
            results.append((name, name))
        elif line.strip() == "":
            in_input = False
    return results
