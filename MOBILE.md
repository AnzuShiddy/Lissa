# Lissa Mobile Apps

Lissa is now available as native Android and iOS apps built with [Capacitor](https://capacitorjs.com/). The same web code powers both platforms, so updates to the web app automatically apply to mobile with a rebuild.

## Prerequisites

### For Android
- Android Studio (free)
- Android SDK 24+ (installed via Android Studio)
- Java Development Kit (JDK) 17+ (installed via Android Studio)
- Node.js and npm (already installed)

### For iOS (macOS only)
- Xcode 15+
- Xcode Command Line Tools
- CocoaPods
- Node.js and npm

## Android Setup & Build

### 1. Install Android Studio

Download from [android.google.com/studio](https://android.google.com/studio). During setup:
- Install Android SDK 24 or later
- Install Android Emulator
- Install Android SDK Platform-Tools

### 2. Set Environment Variables

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):

```bash
export ANDROID_SDK_ROOT=$HOME/Library/Android/sdk  # macOS
# or for Linux:
export ANDROID_SDK_ROOT=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_SDK_ROOT/platform-tools
export JAVA_HOME=/usr/libexec/java_home  # macOS: finds JDK automatically
# or for Linux, find JDK location and add it
```

Then reload your shell:
```bash
source ~/.bashrc  # or ~/.zshrc
```

### 3. Build APK (Unsigned)

The Android project is in the `android/` directory.

```bash
# Copy latest web changes to Android
npm run cap:copy

# Build debug APK
cd android
./gradlew assembleDebug
cd ..
```

The APK will be at: `android/app/build/outputs/apk/debug/app-debug.apk`

### 4. Install on Emulator or Device

**On Android Emulator:**
```bash
# Start Android Studio's emulator (AVD), then:
cd android
./gradlew installDebug
cd ..
```

**On Physical Device:**
1. Enable Developer Options: Settings → About Phone → tap Build Number 7 times
2. Enable USB Debugging: Settings → Developer Options → USB Debugging
3. Connect phone via USB
4. Run: `cd android && ./gradlew installDebug && cd ..`

### 5. Sign & Release APK

For Google Play Store or side-loading:

```bash
cd android
./gradlew assembleRelease
cd ..
```

This requires a keystore file. Create one:

```bash
keytool -genkey -v -keystore ~/lissa-release-key.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 -alias lissa
```

Then sign the APK:
```bash
jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 \
  -keystore ~/lissa-release-key.keystore \
  android/app/build/outputs/apk/release/app-release-unsigned.apk lissa
```

### 6. Upload to Google Play

1. Create a Google Play Developer account ($25 one-time fee)
2. Create the app listing
3. Upload the signed APK to the Internal Testing → Production track
4. Submit for review

## iOS Setup & Build (macOS only)

### 1. Install Xcode

```bash
xcode-select --install  # Command Line Tools
# or full Xcode from App Store
```

### 2. Install CocoaPods

```bash
sudo gem install cocoapods
```

### 3. Add iOS Platform

```bash
npm run cap:add:ios
```

This creates the `ios/` directory with an Xcode project.

### 4. Build & Run

**In Xcode GUI:**
```bash
npm run cap:open:ios
```

This opens Xcode. Select Product → Build and then Product → Run, or let Xcode run it on the simulator.

**Or via command line:**
```bash
cd ios
xcodebuild -workspace App/App.xcworkspace -scheme App -configuration Debug -destination generic/platform=iOS
cd ..
```

### 5. Sign & Deploy

For TestFlight (Apple's beta testing) or App Store:

1. Open the Xcode project: `npm run cap:open:ios`
2. Select the App target → Signing & Capabilities
3. Sign with your Apple Developer Team
4. Product → Archive
5. Distribute via TestFlight or App Store

## Updating Mobile Apps

When you update the web app in `static/`:

```bash
# Copy changes to Android and iOS
npm run cap:sync

# Then rebuild for each platform
npm run cap:build:android
npm run cap:build:ios
```

Or individually:
```bash
npm run cap:copy       # Copy static files
npm run cap:open:android  # Open Android Studio
npm run cap:open:ios      # Open Xcode
```

## Troubleshooting

### Android build fails with "JAVA_HOME not set"
```bash
export JAVA_HOME=/path/to/jdk
# Find it with: which java (then remove /bin/java)
```

### Gradle sync fails
```bash
cd android
./gradlew --stop
./gradlew sync
cd ..
```

### iOS build fails with CocoaPods
```bash
cd ios/App
pod repo update
pod install
cd ../..
```

### Changes to web app don't appear in mobile
```bash
npm run cap:sync  # Copies static files and updates config
```

Then rebuild the native app.

## Capacitor Plugins (Future)

If you want to add native features beyond what the web version offers, use Capacitor plugins:

```bash
npm install @capacitor/camera @capacitor/filesystem
npm run cap:sync
```

Examples:
- `@capacitor/camera` — access device camera
- `@capacitor/filesystem` — read/write files
- `@capacitor/geolocation` — GPS
- `@capacitor/push-notifications` — push notifications

See [Capacitor docs](https://capacitorjs.com/docs/plugins) for the full list.

## Notes

- The Android and iOS apps are built from the same `static/` directory, so web updates automatically sync to mobile (after rebuild).
- The web app at https://lissa-02zl.onrender.com will always be the most up-to-date version.
- For now, the mobile apps use the same public API endpoint. To use a private deployment, edit `capacitor.config.json` and set the `server` field.
- Both apps are currently free to distribute, but App Store submission has a $99/year developer fee; Google Play has a $25 one-time fee.
