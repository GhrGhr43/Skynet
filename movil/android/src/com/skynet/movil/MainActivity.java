package com.skynet.movil;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.graphics.Color;
import android.os.Bundle;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

import org.json.JSONObject;

/** Envoltorio mínimo: la interfaz web de Skynet (assets/www) dentro de un WebView. */
public class MainActivity extends Activity {
    // Las páginas se sirven desde un origen https propio para que funcionen los módulos JS.
    private static final String HOST = "app.skynet.local";
    private static final String START = "https://" + HOST + "/index.html";
    private static final int PIDE_CAMARA = 1;
    private WebView web;
    private PermissionRequest pendiente;   // la página pidió la cámara mientras Android pregunta al usuario
    private String enlace;                 // skynet://emparejar que abrió la app, para dárselo a la página
    private boolean cargada;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setAllowFileAccess(false);
        // Preparado para cuando la app hable con Skynet en el PC por la red local (http).
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                if (!HOST.equals(req.getUrl().getHost())) return null;
                String path = req.getUrl().getPath();
                if (path == null || path.equals("/")) path = "/index.html";
                try {
                    InputStream in = getAssets().open("www" + path);
                    Map<String, String> h = new HashMap<>();
                    h.put("Access-Control-Allow-Origin", "*");
                    h.put("Cache-Control", "no-cache");
                    return new WebResourceResponse(mime(path), "utf-8", 200, "OK", h, in);
                } catch (IOException e) {
                    return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", new HashMap<String, String>(), null);
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                cargada = true;
                entregarEnlace();
            }

            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return !HOST.equals(android.net.Uri.parse(url).getHost());
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            // Solo nuestra propia página puede usar la cámara (para leer el QR del PC), y nada más.
            @Override
            public void onPermissionRequest(final PermissionRequest req) {
                boolean soloVideo = req.getResources().length == 1
                        && PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(req.getResources()[0]);
                if (!soloVideo || !HOST.equals(req.getOrigin().getHost())) {
                    req.deny();
                    return;
                }
                if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    req.grant(req.getResources());
                } else {
                    pendiente = req;
                    requestPermissions(new String[]{Manifest.permission.CAMERA}, PIDE_CAMARA);
                }
            }
        });
        setContentView(web);
        enlace = enlaceDe(getIntent());
        if (state != null) web.restoreState(state); else web.loadUrl(START);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permisos, int[] res) {
        if (code != PIDE_CAMARA || pendiente == null) return;
        if (res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED) pendiente.grant(pendiente.getResources());
        else pendiente.deny();
        pendiente = null;
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String e = enlaceDe(intent);
        if (e != null) {
            enlace = e;
            entregarEnlace();
        }
    }

    private static String enlaceDe(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction())) return null;
        Uri u = intent.getData();
        if (u == null || !"skynet".equals(u.getScheme()) || !"emparejar".equals(u.getHost())) return null;
        return u.toString();
    }

    private void entregarEnlace() {
        if (!cargada || enlace == null) return;
        String js = "window.skynetEnlace && window.skynetEnlace(" + JSONObject.quote(enlace) + ")";
        enlace = null;
        web.evaluateJavascript(js, null);
    }

    private static String mime(String p) {
        if (p.endsWith(".html")) return "text/html";
        if (p.endsWith(".js") || p.endsWith(".mjs")) return "text/javascript";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".woff2")) return "font/woff2";
        if (p.endsWith(".json") || p.endsWith(".webmanifest")) return "application/json";
        return "application/octet-stream";
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        // Primero cierra lo que haya abierto en la interfaz (panel, menú, diálogo); si no hay nada, sale.
        web.evaluateJavascript("window.skynetAtras ? window.skynetAtras() : false", new ValueCallback<String>() {
            @Override
            public void onReceiveValue(String v) {
                if (!"true".equals(v)) finish();
            }
        });
    }

    @Override
    protected void onPause() { super.onPause(); web.onPause(); }

    @Override
    protected void onResume() { super.onResume(); web.onResume(); }
}
