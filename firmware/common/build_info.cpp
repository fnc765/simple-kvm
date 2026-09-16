#include "build_info.h"

#ifndef SIMPLE_KVM_GIT_SHA
#define SIMPLE_KVM_GIT_SHA "unknown"
#endif

#ifndef SIMPLE_KVM_BUILD_PROFILE
#define SIMPLE_KVM_BUILD_PROFILE "unknown"
#endif

namespace simple_kvm {

const char* firmware_git_sha() { return SIMPLE_KVM_GIT_SHA; }
const char* firmware_build_profile() { return SIMPLE_KVM_BUILD_PROFILE; }
const char* firmware_build_timestamp() { return __DATE__ " " __TIME__; }

}  // namespace simple_kvm
