use std::{ffi::c_void, ops::Deref, panic::{catch_unwind, AssertUnwindSafe}, ptr,
          slice, sync::{Arc, RwLock}};
use super::table::{InnerKey, Iterator, Value};

#[repr(C)]
pub struct WriteView {
    key: *const u8, key_len: usize, value: *const u8, value_len: usize,
    version: u64, deleted: u8,
}
#[repr(C)]
pub struct RecordView {
    key: *const u8, key_len: usize, value: *const u8, value_len: usize,
    version: u64, deleted: u8,
}
enum Backend {
    Arena(skl::SkipList, Arc<arena::Arena>),
    Crossbeam(crossbeam_skl::SkipList),
}
struct Table { backend: Backend, frozen: RwLock<bool> }
struct CursorHandle {
    // Drop iterator before its owner, including the borrowed sealed iterator.
    iter: Box<dyn Iterator>,
    _owner: Arc<Table>,
}
fn guarded(f: impl FnOnce() -> i32) -> i32 {
    catch_unwind(AssertUnwindSafe(f)).unwrap_or(-1)
}
// C++ passes valid, non-null buffers even for zero length. No raw view escapes
// the synchronous Get callback; cursor views are owned by CursorHandle.
unsafe fn bytes<'a>(p: *const u8, len: usize) -> &'a [u8] {
    if len == 0 { &[] } else { unsafe { slice::from_raw_parts(p, len) } }
}
fn record(key: &[u8], value: Value) -> RecordView {
    let payload = value.get_value();
    RecordView { key: key.as_ptr(), key_len: key.len(), value: payload.as_ptr(),
                 value_len: payload.len(), version: value.version, deleted: u8::from(value.is_deleted()) }
}
#[no_mangle]
pub extern "C" fn cse_new(crossbeam: u8) -> *mut c_void {
    catch_unwind(|| {
        let backend = if crossbeam != 0 { Backend::Crossbeam(crossbeam_skl::SkipList::new()) }
        else {
            let arena = Arc::new(arena::Arena::new());
            Backend::Arena(skl::SkipList::new(Some(arena.clone())), arena)
        };
        Box::into_raw(Box::new(Arc::new(Table { backend, frozen: RwLock::new(false) }))).cast()
    }).unwrap_or(ptr::null_mut())
}
#[no_mangle]
/// # Safety
/// handle must be a live cse_new result, dropped exactly once without active calls.
pub unsafe extern "C" fn cse_drop(handle: *mut c_void) {
    let _ = guarded(|| { unsafe { drop(Box::from_raw(handle.cast::<Arc<Table>>())) }; 1 });
}
#[no_mangle]
/// # Safety
/// handle must be live. input and every referenced buffer must cover their
/// declared lengths and remain readable throughout the call.
pub unsafe extern "C" fn cse_write(handle: *const c_void, input: *const WriteView, count: usize) -> i32 {
    guarded(|| {
        let table = unsafe { &*handle.cast::<Arc<Table>>() };
        let frozen = table.frozen.read().unwrap();
        if *frozen { return 0; }
        let rows = if count == 0 { &[] } else { unsafe { slice::from_raw_parts(input, count) } };
        let mut size = 0usize;
        for row in rows {
            if row.key_len > u16::MAX as usize || row.value_len > u32::MAX as usize { return -2; }
            size = match size.checked_add(row.key_len + row.value_len) { Some(n) => n, None => return -2 };
            if matches!(table.backend, Backend::Arena(..)) && row.value_len + 10 > arena::MAX_VAL_SIZE as usize { return -2; }
        }
        if size > u32::MAX as usize { return -2; }
        let mut batch = WriteBatch::new();
        for row in rows {
            batch.put(InnerKey::from_inner_buf(unsafe { bytes(row.key, row.key_len) }),
                      u8::from(row.deleted != 0), &[], row.version, unsafe { bytes(row.value, row.value_len) });
        }
        match &table.backend {
            Backend::Arena(list, _) => list.put_batch_preserve_tombstones(&mut batch, 0),
            Backend::Crossbeam(list) => list.put_batch_preserve_tombstones(&mut batch, 0),
        }
        1
    })
}
#[no_mangle]
/// # Safety
/// handle and key must be live/readable. callback must not unwind and must copy
/// views before returning; output must satisfy the callback's own contract.
pub unsafe extern "C" fn cse_get(handle: *const c_void, key: *const u8, len: usize, snapshot: u64,
    output: *mut c_void, callback: extern "C" fn(*mut c_void, *const RecordView)) -> i32 {
    guarded(|| {
        let table = unsafe { &*handle.cast::<Arc<Table>>() };
        let key = unsafe { bytes(key, len) };
        match &table.backend {
            Backend::Arena(list, _) => {
                let value = list.get(key, snapshot);
                if !value.is_valid() { return 0; }
                callback(output, &record(key, value));
            }
            Backend::Crossbeam(list) => {
                let guard = list.get(key, snapshot);
                let value = *guard.value();
                if !value.is_valid() { return 0; }
                callback(output, &record(key, value)); // guard remains alive until copy finishes
            }
        }
        1
    })
}
#[no_mangle]
/// # Safety
/// handle must be a live cse_new result throughout this call.
pub unsafe extern "C" fn cse_freeze(handle: *const c_void) -> i32 {
    guarded(|| {
        let table = unsafe { &*handle.cast::<Arc<Table>>() };
        let mut frozen = table.frozen.write().unwrap();
        if let Backend::Crossbeam(list) = &table.backend { list.seal(); }
        *frozen = true;
        1
    })
}
#[no_mangle]
/// # Safety
/// handle must be live during creation. The result must be dropped exactly once
/// with cse_cursor_drop. A flush cursor requires a permanently frozen table.
pub unsafe extern "C" fn cse_cursor_new(handle: *const c_void, flush: u8) -> *mut c_void {
    catch_unwind(AssertUnwindSafe(|| {
        let table = unsafe { &*handle.cast::<Arc<Table>>() }.clone();
        assert!(flush == 0 || *table.frozen.read().unwrap(), "flush requires Freeze");
        let iter: Box<dyn Iterator + '_> = match &table.backend {
            Backend::Arena(list, _) => Box::new(list.new_iterator(false)),
            Backend::Crossbeam(list) if flush != 0 => Box::new(list.new_flush_iterator()),
            Backend::Crossbeam(list) => Box::new(list.new_iterator(false)),
        };
        // SAFETY: Arc<Table> has a stable heap address and CursorHandle retains
        // it. The borrowed flush iterator is dropped BEFORE _owner. Freeze is
        // permanent and the write gate prevents subsequent Arena writes too.
        let iter = unsafe { std::mem::transmute::<Box<dyn Iterator + '_>, Box<dyn Iterator>>(iter) };
        Box::into_raw(Box::new(CursorHandle { iter, _owner: table })).cast()
    })).unwrap_or(ptr::null_mut())
}
#[no_mangle]
/// # Safety
/// handle must be a live cse_cursor_new result with no active cursor calls/views.
pub unsafe extern "C" fn cse_cursor_drop(handle: *mut c_void) {
    let _ = guarded(|| { unsafe { drop(Box::from_raw(handle.cast::<CursorHandle>())) }; 1 });
}
#[no_mangle]
/// # Safety
/// Cursor must be live and exclusively accessed; key must cover len bytes.
pub unsafe extern "C" fn cse_cursor_seek(handle: *mut c_void, key: *const u8, len: usize) -> i32 {
    guarded(|| {
        let cursor = unsafe { &mut *handle.cast::<CursorHandle>() };
        cursor.iter.seek(InnerKey::from_inner_buf(unsafe { bytes(key, len) }));
        i32::from(cursor.iter.valid())
    })
}
#[no_mangle]
/// # Safety
/// Cursor must be live and exclusively accessed, with no borrowed view in use.
pub unsafe extern "C" fn cse_cursor_next(handle: *mut c_void, version: u8) -> i32 {
    guarded(|| {
        let cursor = unsafe { &mut *handle.cast::<CursorHandle>() };
        if !cursor.iter.valid() { return 0; }
        if version != 0 { return i32::from(cursor.iter.next_version()); }
        cursor.iter.next();
        i32::from(cursor.iter.valid())
    })
}
#[no_mangle]
/// # Safety
/// Cursor must be live and exclusively accessed. out must be writable/aligned.
/// Returned views expire on the next cursor navigation or destruction.
pub unsafe extern "C" fn cse_cursor_record(handle: *const c_void, out: *mut RecordView) -> i32 {
    guarded(|| {
        let cursor = unsafe { &*handle.cast::<CursorHandle>() };
        if !cursor.iter.valid() { return 0; }
        unsafe { *out = record(cursor.iter.key().deref(), cursor.iter.value()); }
        1
    })
}
#[no_mangle]
/// # Safety
/// handle must be a live cse_new result throughout this call.
pub unsafe extern "C" fn cse_retained(handle: *const c_void) -> u64 {
    catch_unwind(AssertUnwindSafe(|| {
        let table = unsafe { &*handle.cast::<Arc<Table>>() };
        match &table.backend {
            Backend::Arena(_, arena) => arena.size() as u64,
            Backend::Crossbeam(list) => list.memory_usage(),
        }
    })).unwrap_or(0)
}
