# Tauri Prerequisites

## Ubuntu Build Host
```bash
sudo apt-get update
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev \
  librsvg2-dev \
  patchelf \
  build-essential \
  curl \
  wget \
  file \
  libxdo-dev \
  libssl-dev \
  libayatana-appindicator3-dev \
  librsvg2-common
```

Install Rust toolchain:
```bash
curl https://sh.rustup.rs -sSf | sh -s -- -y
source "$HOME/.cargo/env"
rustc --version
cargo --version
```

Then verify:
```bash
npm --prefix apps/desktop run tauri:info
npm --prefix apps/desktop run build -- --debug
```

## Windows note
For native Windows builds, install:
- Visual Studio Build Tools (Desktop C++)
- WebView2 Runtime
- Rust toolchain (`rustup`)

GNU path used by current build (no MSVC required):
```powershell
winget install -e --id MSYS2.MSYS2 --silent
```

Then install GNU binutils/gcc in MSYS2:
```powershell
C:\msys64\usr\bin\bash.exe -lc "pacman -Sy --noconfirm --needed mingw-w64-ucrt-x86_64-binutils mingw-w64-ucrt-x86_64-gcc"
```

Build with GNU toolchain path:
```powershell
cd apps\desktop
npm run build:debug:no-bundle:win-gnu
```

Note:
- `tauri build` (bundle mode) may download WiX from GitHub; if your network blocks it, use `--no-bundle` first.
