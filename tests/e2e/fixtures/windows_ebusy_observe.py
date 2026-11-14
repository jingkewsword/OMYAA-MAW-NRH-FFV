import ctypes, json, sys
from ctypes import wintypes

k = ctypes.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k.OpenProcess.restype = wintypes.HANDLE
k.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k.CloseHandle.argtypes = [wintypes.HANDLE]
def process_info(pid):
    h = k.OpenProcess(0x1000, False, pid)
    if not h: return {'pid': pid, 'status': 'unavailable', 'error': ctypes.get_last_error()}
    try:
        creation, end, kernel, user = (wintypes.FILETIME() for _ in range(4))
        code = wintypes.DWORD()
        if not k.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(end), ctypes.byref(kernel), ctypes.byref(user)) or not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return {'pid': pid, 'status': 'query_failed', 'error': ctypes.get_last_error()}
        return {'pid': pid, 'creation_filetime': str((creation.dwHighDateTime << 32) | creation.dwLowDateTime), 'exit_code': code.value, 'status': 'running' if code.value == 259 else 'exited'}
    finally: k.CloseHandle(h)

class Unique(ctypes.Structure):
    _fields_ = [('pid', wintypes.DWORD), ('started', wintypes.FILETIME)]
class Proc(ctypes.Structure):
    _fields_ = [('process', Unique), ('app', wintypes.WCHAR * 256), ('service', wintypes.WCHAR * 64), ('kind', ctypes.c_int), ('status', wintypes.ULONG), ('session', wintypes.DWORD), ('restartable', wintypes.BOOL)]
def locks(path):
    rm = ctypes.WinDLL('rstrtmgr', use_last_error=True)
    session = wintypes.DWORD(); key = ctypes.create_unicode_buffer(33)
    code = rm.RmStartSession(ctypes.byref(session), 0, key)
    if code: return {'status': 'query_failed', 'stage': 'start', 'code': code}
    try:
        names = (wintypes.LPCWSTR * 1)(path)
        code = rm.RmRegisterResources(session, 1, names, 0, None, 0, None)
        if code: return {'status': 'query_failed', 'stage': 'register', 'code': code}
        needed = wintypes.UINT(); count = wintypes.UINT(); reason = wintypes.DWORD()
        code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        if code == 0: return {'status': 'unknown', 'processes': []}
        if code != 234: return {'status': 'query_failed', 'stage': 'size', 'code': code}
        array = (Proc * needed.value)(); count.value = needed.value
        code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), array, ctypes.byref(reason))
        if code: return {'status': 'query_failed', 'stage': 'list', 'code': code}
        processes = [{'pid': p.process.pid, 'creation_filetime': str((p.process.started.dwHighDateTime << 32) | p.process.started.dwLowDateTime), 'name': p.app, 'service': p.service} for p in array[:count.value]]
        return {'status': 'found' if processes else 'unknown', 'processes': processes}
    finally: rm.RmEndSession(session)

if __name__ == '__main__':
    mode = sys.argv[1]
    print(json.dumps(locks(sys.argv[2]) if mode == 'locks' else [process_info(int(pid)) for pid in sys.argv[2:] if int(pid) > 0]))
