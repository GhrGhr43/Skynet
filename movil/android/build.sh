#!/bin/sh
# Compila el APK sin Gradle: aapt + javac + dx + zipalign + apksigner.
# Uso: build.sh <carpeta-www> <keystore> <salida.apk>   (contraseña en $SKYNET_KS_PASS)
set -e
A=$(cd "$(dirname "$0")" && pwd); WWW=$1; KS=$2; OUT=$3
JAR=/usr/lib/android-sdk/platforms/android-23/android.jar
B=$(mktemp -d)
mkdir -p "$B/gen" "$B/classes" "$B/assets"
cp -r "$WWW" "$B/assets/www"
aapt package -f -m -J "$B/gen" -M "$A/AndroidManifest.xml" -S "$A/res" -I "$JAR"
javac -nowarn -Xlint:-options -source 8 -target 8 -bootclasspath "$JAR" -d "$B/classes" "$A"/src/com/skynet/movil/*.java "$B"/gen/com/skynet/movil/R.java
dalvik-exchange --dex --min-sdk-version=24 --output="$B/classes.dex" "$B/classes"
aapt package -f -M "$A/AndroidManifest.xml" -S "$A/res" -A "$B/assets" -I "$JAR" -F "$B/sin-firmar.apk"
(cd "$B" && aapt add sin-firmar.apk classes.dex >/dev/null)
zipalign -f -p 4 "$B/sin-firmar.apk" "$B/alineado.apk"
apksigner sign --ks "$KS" --ks-pass env:SKYNET_KS_PASS --out "$OUT" "$B/alineado.apk"
apksigner verify --print-certs "$OUT" | head -2
rm -rf "$B"
