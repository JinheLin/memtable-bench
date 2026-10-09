#include "memtable_bench/mvcc.h"
#include <atomic>
#include <barrier>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <mutex>

namespace mb = memtable_bench;
void CheckAt(bool ok, int line) {
  if (!ok) throw std::runtime_error("MVCC contract failed at line " + std::to_string(line));
}
#define Check(condition) CheckAt(condition, __LINE__)
std::string Key(unsigned id) { return mb::EncodeKey(id,8,false); }
void Contract(const mb::AdapterInfo& info) {
  auto table=mb::MakeMvccTable(info.name,8);
  const auto a=Key(1),b=Key(2),c=Key(3);
  const mb::MvccWrite rows[]={{a,"a1",1},{b,"b2",2},{a,"a3",3},
                            {a,"",4,true},{c,"",5},{a,"a6",6}};
  Check(table->Write(rows));
  mb::MvccValue value;
  Check(!table->GetAt(a,0,&value));
  Check(table->GetAt(a,2,&value) && value.value=="a1" && value.version==1 && !value.deleted);
  Check(table->GetAt(a,5,&value) && value.deleted && value.version==4);
  Check(table->GetAt(a,UINT64_MAX,&value) && value.value=="a6" && value.version==6);
  Check(table->GetAt(c,5,&value) && value.value.empty() && !value.deleted);
  Check(!table->GetAt(Key(4),100,&value));
  auto cursor=table->NewCursor();
  Check(cursor->Seek(a) && cursor->Key()==a && cursor->Version()==6);
  Check(cursor->NextVersion() && cursor->Version()==4 && cursor->Deleted());
  Check(cursor->NextVersion() && cursor->Version()==3);
  Check(cursor->NextVersion() && cursor->Version()==1);
  Check(!cursor->NextVersion() && cursor->Version()==1);
  Check(cursor->NextUser() && cursor->Key()==b && cursor->Version()==2);
  Check(!cursor->NextVersion() && cursor->Key()==b);
  std::uint64_t hash=1469598103934665603ULL, expected=hash;
  std::size_t examined=0;
  mb::HashRecord(b,"b2",2,false,&expected);
  mb::HashRecord(c,"",5,false,&expected);
  Check(mb::VisibleScan(*table,a,5,20,&hash,&examined)==2 && hash==expected);
  cursor.reset();
  if (info.native_concurrent) {
    std::atomic<bool> failed=false;
    std::mutex error_mu;
    std::string error;
    std::barrier start(4);
    std::vector<std::thread> readers;
    for (int i=0;i<3;++i) readers.emplace_back([&] {
      try {
        start.arrive_and_wait();
        for (int j=0;j<200;++j) {
          mb::MvccValue v;
          Check(table->GetAt(a,3,&v) && v.value=="a3" && v.version==3);
          auto iter=table->NewCursor();
          Check(iter->Seek(a));
          while (iter->Version()>3 && iter->NextVersion()) {}
          if (iter->Version()!=3 || iter->Value()!="a3")
            throw std::runtime_error("historical cursor: version=" +
                std::to_string(iter->Version()) + ", value=" + std::string(iter->Value()) +
                ", expected version=3, value=a3");
        }
      } catch (const std::exception& e) {
        failed=true;
        std::lock_guard lock(error_mu); error=e.what();
      }
    });
    start.arrive_and_wait();
    for (std::uint64_t ts=7;ts<107;++ts) {
      const mb::MvccWrite row{a,"new",ts}; Check(table->Write(std::span(&row,1)));
      std::this_thread::yield();
    }
    for (auto& thread:readers) thread.join();
    if (failed) throw std::runtime_error(info.name + ": " + error);
  }
  table->Freeze();
  const mb::MvccWrite rejected{a,"bad",200};
  Check(!table->Write(std::span(&rejected,1)));
  hash=1469598103934665603ULL;
  Check(mb::FlushVersions(*table,&hash)==table->VersionCount());
  std::cout << info.name << " MVCC contract passed\n";
}
void Oversized(const mb::AdapterInfo& info) {
  if (!info.name.starts_with("cse_")) return;
  auto table=mb::MakeMvccTable(info.name,8);
  const auto key=Key(1);
  std::string payload(16*1024*1024,'x');
  const mb::MvccWrite row{key,payload,1};
  Check(table->Write(std::span(&row,1)));
  mb::MvccValue value;
  Check(table->GetAt(key,1,&value) && value.value==payload);
  table->Freeze();
  auto cursor=table->NewCursor(true);
  Check(cursor->Seek(key) && cursor->Value()==payload && cursor->Version()==1);
}
int main() {
  try {
    for (const auto& info:mb::ListMvccAdapters()) if (info.available) { Contract(info); Oversized(info); }
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
