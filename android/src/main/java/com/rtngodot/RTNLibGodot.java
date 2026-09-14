/**************************************************************************/
/*  RTNLibGodot.java                                                      */
/**************************************************************************/
/* Copyright (c) 2024-2025 Slay GmbH                                      */
/*                                                                        */
/* Permission is hereby granted, free of charge, to any person obtaining  */
/* a copy of this software and associated documentation files (the        */
/* "Software"), to deal in the Software without restriction, including    */
/* without limitation the rights to use, copy, modify, merge, publish,    */
/* distribute, sublicense, and/or sell copies of the Software, and to     */
/* permit persons to whom the Software is furnished to do so, subject to  */
/* the following conditions:                                              */
/*                                                                        */
/* The above copyright notice and this permission notice shall be         */
/* included in all copies or substantial portions of the Software.        */
/*                                                                        */
/* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,        */
/* EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF     */
/* MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. */
/* IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY   */
/* CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,   */
/* TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE      */
/* SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                 */
/**************************************************************************/

package com.rtngodot;

import android.app.Activity;
import android.content.res.AssetManager;
import android.graphics.PixelFormat;
import android.util.DisplayMetrics;
import android.view.Surface;
import android.view.SurfaceControl;
import android.view.SurfaceHolder;
import android.util.Log;
import androidx.annotation.NonNull;
import org.godotengine.godot.Godot;
import org.godotengine.godot.GodotHost;
import org.godotengine.godot.GodotIO;
import org.godotengine.godot.io.directory.DirectoryAccessHandler;
import org.godotengine.godot.io.file.FileAccessHandler;
import org.godotengine.godot.utils.GodotNetUtils;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

/** Supplies Android services and surfaces; React Native owns Activity and UI lifecycle. */
public class RTNLibGodot implements GodotHost {
    private static final String TAG = "LibGodot";
    private static final RTNLibGodot INSTANCE = new RTNLibGodot();
    private Activity activity;
    private boolean inited;
    private Godot godot;
    public static RTNLibGodot getInstance() { return INSTANCE; }
    @Override public Activity getActivity() { return activity; }
    @Override public Godot getGodot() { return godot; }
	private static class WindowSurfaceData {
		public SurfaceControl attachedControl;
		public Surface attachedSurface;
		public final SurfaceControl control;
		public final Surface surface;
		public final boolean persistent;
		public int width;
		public int height;

		public WindowSurfaceData(SurfaceControl ctrl, int width, int height, boolean persistent) {
			this.control = ctrl;
			this.surface = new Surface(ctrl);
			this.width = width;
			this.height = height;
			this.persistent = persistent;
		}
	}

	private static final Map<String, WindowSurfaceData> windowData = new HashMap<>();

	private static void createWindowSurface(String name, int width, int height) {
		SurfaceControl.Builder b = new SurfaceControl.Builder();
		SurfaceControl control = b.setBufferSize(width, height)
										 .setFormat(PixelFormat.RGBA_8888)
										 .setName(name)
										 .build();

		WindowSurfaceData wsData = new WindowSurfaceData(control, width, height, name.isEmpty());

		windowData.put(name, wsData);
	}

	@NonNull
	private static WindowSurfaceData getOrCreateWindowSurface(String name, int width, int height) {
		WindowSurfaceData wsData = windowData.get(name);
		if (wsData == null) {
			createWindowSurface(name, width, height);
			wsData = Objects.requireNonNull(windowData.get(name));
		}
		return wsData;
	}

	public void updateWindow(String name, SurfaceControl control, SurfaceHolder holder, int format, int width, int height) {
		if (!"".equals(name)) {
			// Render in the window surface directly
			updateWindowNative(name, holder.getSurface(), width, height);
			return;
		}

		WindowSurfaceData wsData = getOrCreateWindowSurface(name, width, height);

		if (wsData.attachedControl == null || wsData.attachedSurface == null || !wsData.attachedControl.equals(control) || !wsData.attachedSurface.equals(holder.getSurface())) {
			if (wsData.attachedControl != null) {
				wsData.attachedControl = null;
				wsData.attachedSurface = null;
			}
			Log.i(TAG, String.format("Attaching and resizing surface to: %d %d", width, height));
			try (SurfaceControl.Transaction t = new SurfaceControl.Transaction()) {
				// Set new parent
				t.reparent(wsData.control, control);
				t.setLayer(wsData.control, 1);
				t.setVisibility(wsData.control, true);
				if (wsData.width != width || wsData.height != height) {
					t.setBufferSize(wsData.control, width, height);
					wsData.width = width;
					wsData.height = height;
				}
				t.apply();
			}

			wsData.attachedControl = control;
			wsData.attachedSurface = holder.getSurface();
		} else if (wsData.width != width || wsData.height != height) {
			Log.i(TAG, String.format("Resizing surface to: %d %d", width, height));
			try (SurfaceControl.Transaction t = new SurfaceControl.Transaction()) {
				t.setBufferSize(wsData.control, width, height);
				wsData.width = width;
				wsData.height = height;
				t.apply();
			}
		}

		updateWindowNative(name, wsData.surface, width, height);
	}

	public void removeWindow(String name, SurfaceControl owner) {
		WindowSurfaceData wsData = windowData.get(name);
        if (wsData != null && wsData.attachedControl != null && !wsData.attachedControl.equals(owner)) return;
		if (wsData != null) {
			try (SurfaceControl.Transaction t = new SurfaceControl.Transaction()) {
				t.reparent(wsData.control, null);
				t.setVisibility(wsData.control, false);
				t.apply();
			}
			wsData.attachedControl = null;
			wsData.attachedSurface = null;

			removeWindowNative(name);

			if (!wsData.persistent) {
				windowData.remove(name);
			}
		} else {
			removeWindowNative(name);
		}
	}


    public synchronized void init(Activity host) {
        if (host == null) throw new IllegalStateException("Godot requires an attached Activity");
        activity = host;
        if (inited) return;
        DisplayMetrics metrics = host.getResources().getDisplayMetrics();
        WindowSurfaceData window = getOrCreateWindowSurface("", metrics.widthPixels, metrics.heightPixels);
        godot = Godot.getInstance(host);
        Object nativeBridge = godot.prepareEmbeddedHost(this);
        initialize(host.getAssets(), godot.getNetUtils(), godot.getDirectoryAccessHandler(),
            godot.getFileAccessHandler(), godot.getIo(), window.surface, window.width, window.height,
            nativeBridge, host, RTNLibGodot.class.getClassLoader());
        inited = true;
    }
    private static native void initialize(AssetManager assets, GodotNetUtils net,
        DirectoryAccessHandler dirs, FileAccessHandler files, GodotIO io,
        Surface surface, int width, int height, Object godotBridge, Activity host, ClassLoader loader);
    public native void dispatchTouchEvent(String name, int event, int pointer, int count, float[] positions, boolean doubleTap);
    private native void updateWindowNative(String name, Surface surface, int width, int height);
    private native void removeWindowNative(String name);
}
