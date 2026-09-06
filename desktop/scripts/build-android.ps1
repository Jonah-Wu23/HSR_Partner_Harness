[CmdletBinding()]
param([switch]$Offline)

$ErrorActionPreference = "Stop"
$desktopRoot = Split-Path -Parent $PSScriptRoot
$tauriRoot = Join-Path $desktopRoot "src-tauri"
$androidRoot = Join-Path $tauriRoot "gen/android"
$ndkBin = Join-Path $env:NDK_HOME "toolchains/llvm/prebuilt/windows-x86_64/bin"
$linker = Join-Path $ndkBin "aarch64-linux-android24-clang.cmd"
foreach ($required in @((Join-Path $env:JAVA_HOME "bin/java.exe"), $linker, (Join-Path $env:ANDROID_HOME "platforms/android-36/android.jar"))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Android build dependency missing: $required"
    }
}

Push-Location $desktopRoot
try {
    & npm.cmd --prefix mobile run build
    if ($LASTEXITCODE -ne 0) { throw "Mobile frontend build failed: $LASTEXITCODE" }
} finally { Pop-Location }

# Tauri custom-protocol embeds frontendDist in the Rust library. An existing .so
# or copying files into APK assets alone is not proof that new UI code is included.
$env:CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER = $linker
$env:CC_aarch64_linux_android = $linker
$env:CXX_aarch64_linux_android = Join-Path $ndkBin "aarch64-linux-android24-clang++.cmd"
$env:AR_aarch64_linux_android = Join-Path $ndkBin "llvm-ar.exe"
$env:TAURI_ANDROID_PROJECT_PATH = $androidRoot
Push-Location $tauriRoot
try {
    $cargoArgs = @("build", "--lib", "--target", "aarch64-linux-android", "--features", "tauri/custom-protocol", "--locked")
    if ($Offline) { $cargoArgs += "--offline" }
    & cargo @cargoArgs
    if ($LASTEXITCODE -ne 0) { throw "Android Rust build failed: $LASTEXITCODE" }
} finally { Pop-Location }

$library = Join-Path $tauriRoot "target/aarch64-linux-android/debug/libhsr_partner_harness_lib.so"
$jniDir = Join-Path $androidRoot "app/src/main/jniLibs/arm64-v8a"
New-Item -ItemType Directory -Path $jniDir -Force | Out-Null
$jniLibrary = Join-Path $jniDir "libhsr_partner_harness_lib.so"
$existingLibrary = Get-Item -LiteralPath $jniLibrary -ErrorAction SilentlyContinue
if ($existingLibrary -and $existingLibrary.LinkType -eq "SymbolicLink") {
    if ([IO.Path]::GetFullPath($existingLibrary.Target) -ne [IO.Path]::GetFullPath($library)) {
        throw "JNI symlink points to an unexpected library: $($existingLibrary.Target)"
    }
    # Tauri may already have linked JNI to this exact cargo output.
} else {
    Copy-Item -LiteralPath $library -Destination $jniDir -Force
}
$libraryHash = (Get-FileHash -LiteralPath $library -Algorithm SHA256).Hash.ToLowerInvariant()

$assetsPath = [IO.Path]::GetFullPath((Join-Path $androidRoot "app/src/main/assets"))
$expectedAssets = [IO.Path]::GetFullPath((Join-Path $desktopRoot "src-tauri/gen/android/app/src/main/assets"))
if ($assetsPath -ne $expectedAssets -or -not $assetsPath.StartsWith([IO.Path]::GetFullPath($desktopRoot) + [IO.Path]::DirectorySeparatorChar)) {
    throw "Refusing to replace assets outside the Android build directory: $assetsPath"
}
if (Test-Path -LiteralPath $assetsPath) { Remove-Item -LiteralPath $assetsPath -Recurse -Force }
New-Item -ItemType Directory -Path $assetsPath -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $desktopRoot "mobile/dist") | Copy-Item -Destination $assetsPath -Recurse -Force

Push-Location $androidRoot
try {
    $gradleArgs = @("--console=plain", ":app:assembleArm64Debug", "-PpairHarnessPrebuiltLibrarySha256=$libraryHash")
    if ($Offline) { $gradleArgs += "--offline" }
    & .\gradlew.bat @gradleArgs
    if ($LASTEXITCODE -ne 0) { throw "Android APK build failed: $LASTEXITCODE" }
} finally { Pop-Location }
Write-Host "Built APK: $(Join-Path $androidRoot 'app/build/outputs/apk/arm64/debug/app-arm64-debug.apk')"
