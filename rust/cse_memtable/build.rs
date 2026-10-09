use std::{env, fs, path::PathBuf};

fn main() {
    println!("cargo:rerun-if-env-changed=CSE_MEMTABLE_EXPORT");
    let root = PathBuf::from(env::var("CSE_MEMTABLE_EXPORT").expect("set CSE_MEMTABLE_EXPORT"));
    let mut modules = String::new();
    // Crossbeam reuses WriteBatch/WriteBatchEntry from skl; skl imports arena.
    // These unchanged dependency modules do not expose an Arena C ABI backend.
    for name in ["arena", "skl", "crossbeam_skl"] {
        let path = root.join(format!("{name}.rs")).canonicalize().unwrap();
        println!("cargo:rerun-if-changed={}", path.display());
        modules.push_str(&format!("#[path = {:?}] pub mod {name};\n", path));
    }
    modules.push_str("pub use skl::{WriteBatch, WriteBatchEntry};\n");
    fs::write(PathBuf::from(env::var("OUT_DIR").unwrap()).join("modules.rs"), modules).unwrap();
}
