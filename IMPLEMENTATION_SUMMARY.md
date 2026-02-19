# Implementation Summary: thz.read_raw_register Service

## Overview
This PR implements a new Home Assistant service `thz.read_raw_register` to help users and developers debug firmware-specific register issues in Stiebel Eltron / Tecalor THZ heat pumps.

## Problem Addressed
Users with firmware versions like FW 709 (issues #82, #83) report incorrect values for bit-decoded sensors from registers like `sDisplay` (`0A0176`). Previously, there was no way for users to inspect raw heatpump response data without enabling debug logging and manually parsing log files.

## Solution Implemented

### 1. New Service: `thz.read_raw_register`
**File**: `custom_components/thz/services.yaml`
- Accepts hex command strings (e.g., "FB", "0A0176", "F2")
- Validates input and provides helpful examples
- Integrated into Home Assistant service UI

### 2. Service Implementation
**File**: `custom_components/thz/__init__.py`

**Key Components**:
- `_async_setup_services()`: Idempotent service registration
- `_async_handle_read_raw_register()`: Service handler with:
  - Hex string validation
  - Device lock acquisition (thread-safe)
  - Async executor wrapping for blocking I/O
  - Comprehensive error handling
  - Three output methods:
    1. Service response (for automation)
    2. Persistent notification (for UI users)
    3. INFO-level logging (for developers)

**Service Registration Details**:
- Supports optional service responses (`SupportsResponse.OPTIONAL`)
- Uses voluptuous schema for validation
- Properly cleans up when last config entry is removed

**Output Format**:
```
  0000: 01 0a 07 05 03 00 12 34 ff 00 12 34 56 78 9a bc
  0010: de f0 12 34 56 78 9a bc de f0 12 34 56 78 9a
```

### 3. Diagnostics Extension
**File**: `custom_components/thz/diagnostics.py`

Added `raw_blocks` section to diagnostics output:
```json
{
  "raw_blocks": {
    "pxxFB": {
      "hex": "010a070503001234...",
      "length": 45
    },
    "pxx0A0176": {
      "hex": "ff00123456...",
      "length": 42
    }
  }
}
```

Benefits:
- Automatically includes all coordinator data
- Helps users share register dumps when reporting issues
- No manual service calls needed for diagnostics

### 4. Comprehensive Testing
**Files**: 
- `tests/test_service_read_raw_register.py` (11 tests)
- `tests/test_diagnostics_raw_blocks.py` (4 tests)
- `tests/conftest.py` (mock updates)

**Test Coverage**:
- Service registration and idempotency
- Successful reads with formatted output
- Error handling (invalid hex, no device, communication errors)
- Service cleanup on unload
- Diagnostics raw block inclusion
- Edge cases (empty data, large blocks)

**Results**: 15/15 tests passing, no regressions

### 5. User Documentation
**File**: `docs/read-raw-register-service.md`

Includes:
- How to use the service (UI, YAML, automation)
- Common register commands reference
- Output format examples
- Troubleshooting guide
- Instructions for sharing data with developers

## Code Quality

### Linting
- All ruff checks pass
- PEP 8 compliant
- Type hints throughout
- Named constants for magic numbers
- Comprehensive docstrings

### Architecture
- Follows Home Assistant patterns
- Minimal changes to existing code
- No modifications to `thz_device.py` required
- Reuses existing `read_block()` method
- Thread-safe with device.lock
- Proper async/sync boundaries

### Review Feedback
- ✅ Extracted magic number (16) to `BYTES_PER_HEX_LINE` constant
- ✅ Added clear documentation for hex dump formatting
- ✅ All review comments addressed

## Use Cases

### Issue #82: filterDown incorrect on FW 709
Users can run:
```yaml
service: thz.read_raw_register
data:
  command: "0A0176"
```
To get the raw `sDisplay` register and verify byte layout.

### Issue #83: service value wrong on FW 709
Same command helps diagnose service value issues.

### Issue #85: pump sensors not updating
Users can run:
```yaml
service: thz.read_raw_register
data:
  command: "FB"
```
To check if pump data exists at expected offsets in `sGlobal`.

## Statistics
- **Files Modified**: 3
- **Files Created**: 4
- **Lines Added**: 840
- **Lines Removed**: 7
- **Tests Added**: 15 (all passing)
- **Test Coverage**: 100% of new code

## Commits
1. `5d1eb2d` - Add thz.read_raw_register service with diagnostics extension
2. `f5db615` - Add comprehensive tests for read_raw_register service and diagnostics
3. `53dc631` - Fix linting errors in __init__.py and diagnostics.py
4. `5a1e06f` - Extract magic number to BYTES_PER_HEX_LINE constant and add documentation

## Ready for Merge
- ✅ All requirements met
- ✅ All tests passing
- ✅ Linting clean
- ✅ Code review feedback addressed
- ✅ Documentation complete
- ✅ No breaking changes
- ✅ Backward compatible
