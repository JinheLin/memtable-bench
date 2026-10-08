//! Compatibility types and C ABI around unmodified, pinned CSE MemTable files.
//! Raw benchmark keys are already inner keys: TiKV API V2 prefix parsing, blobs,
//! SST snapshots, engine metrics, transactions and other CFs are outside scope.
#![allow(dead_code)]
macro_rules! error { ($($arg:tt)*) => { eprintln!($($arg)*); } }

pub struct SnapAccess;
impl SnapAccess {
    pub fn is_cf_sync(&self, _: usize) -> bool { unreachable!("benchmark preserves tombstones") }
    pub fn contains_in_older_table(&self, _: table::InnerKey<'_>, _: usize) -> bool { unreachable!() }
}
mod metrics {
    pub struct Histogram;
    impl Histogram { pub fn observe(&self, _: f64) {} }
    pub static ENGINE_ARENA_GROW_DURATION_HISTOGRAM: Histogram = Histogram;
    pub fn elapsed_secs(start: std::time::Instant) -> f64 { start.elapsed().as_secs_f64() }
}
pub mod table {
    pub use table::{InnerKey, is_deleted};
    #[allow(clippy::module_inception)] // Match the original core's import paths.
    pub mod table {
        use std::{ops::Deref, ptr, slice};
        pub const VALUE_VERSION_OFF: usize = 2;
        pub const VALUE_VERSION_LEN: usize = 8;
        pub fn is_deleted(meta: u8) -> bool { meta & 1 != 0 }
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
        pub struct InnerKey<'a>(&'a [u8]);
        impl<'a> InnerKey<'a> {
            pub fn from_inner_buf(bytes: &'a [u8]) -> Self { Self(bytes) }
        }
        impl Deref for InnerKey<'_> {
            type Target = [u8];
            fn deref(&self) -> &[u8] { self.0 }
        }
        // CSE-compatible borrowed metadata view. Owners in the native core
        // determine its lifetime; this bridge never exports an unowned Get view.
        #[derive(Clone, Copy, Debug)]
        pub struct Value {
            ptr: *const u8, len: usize, user_meta_len: usize,
            separate: *const u8, pub meta: u8, pub version: u64,
        }
        impl Default for Value { fn default() -> Self { Self::new() } }
        impl Value {
            pub fn new() -> Self {
                Self { ptr: ptr::null(), separate: ptr::null(), len: 0, user_meta_len: 0, meta: 0, version: 0 }
            }
            pub fn decode(buf: &[u8]) -> Self {
                let user_meta_len = buf[1] as usize;
                Self { ptr: buf[10..].as_ptr(), separate: ptr::null(), len: buf.len()-10-user_meta_len,
                       user_meta_len, meta: buf[0], version: u64::from_le_bytes(buf[2..10].try_into().unwrap()) }
            }
            pub fn decode_with_separate_value(preamble: &[u8], value: &[u8]) -> Self {
                let mut result = Self::decode(preamble);
                result.len = value.len(); result.separate = value.as_ptr(); result
            }
            pub fn is_empty(&self) -> bool { self.meta == 0 && self.ptr.is_null() }
            pub fn is_valid(&self) -> bool { !self.is_empty() }
            pub fn is_deleted(&self) -> bool { is_deleted(self.meta) }
            pub fn is_blob_ref(&self) -> bool { self.meta & 4 != 0 }
            pub fn get_value(&self) -> &[u8] {
                if self.len == 0 { return &[]; }
                unsafe { slice::from_raw_parts(if self.separate.is_null() { self.ptr.add(self.user_meta_len) } else { self.separate }, self.len) }
            }
        }
        pub trait Iterator: Send {
            fn next(&mut self);
            fn next_version(&mut self) -> bool;
            fn rewind(&mut self);
            fn seek(&mut self, key: InnerKey<'_>);
            fn key(&self) -> InnerKey<'_>;
            fn value(&self) -> Value;
            fn valid(&self) -> bool;
            #[cfg(debug_assertions)] fn tag(&self) -> String;
        }
    }
    pub mod memtable {
        include!(concat!(env!("OUT_DIR"), "/modules.rs"));
        include!("ffi.rs");
    }
}
