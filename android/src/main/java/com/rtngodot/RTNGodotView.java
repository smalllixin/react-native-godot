/**************************************************************************/
/*  RTNGodotView.java                                                     */
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

import android.annotation.SuppressLint;
import android.content.Context;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.ViewGroup;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

/** One composited world surface. Its removal never owns engine destruction. */
public class RTNGodotView extends SurfaceView implements SurfaceHolder.Callback2 {
    private String windowName = "";
    private MotionEvent lastTouch;
    private boolean surfaceAvailable;
    public RTNGodotView(Context context) { super(context); configure(); }
    public RTNGodotView(Context context, @Nullable AttributeSet attrs) { super(context, attrs); configure(); }
    public RTNGodotView(Context context, @Nullable AttributeSet attrs, int style) { super(context, attrs, style); configure(); }
    private void configure() {
        setLayoutParams(new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        getHolder().addCallback(this);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
    }
    public void setWindowName(String name) { if (!windowName.equals(name)) cancelTouches(); windowName = name; }
    public String getWindowName() { return windowName; }
    @Override public void surfaceRedrawNeeded(@NonNull SurfaceHolder holder) {}
    @Override public void surfaceCreated(@NonNull SurfaceHolder holder) {}
    @Override public void surfaceChanged(@NonNull SurfaceHolder holder,int format,int width,int height) {
        surfaceAvailable = true;
        RTNLibGodot.getInstance().updateWindow(windowName,getSurfaceControl(),holder,format,width,height);
    }
    @Override public void surfaceDestroyed(@NonNull SurfaceHolder holder) {
        cancelTouches(); surfaceAvailable = false; RTNLibGodot.getInstance().removeWindow(windowName, getSurfaceControl());
    }
    private void forward(MotionEvent event, int action) {
        int count=event.getPointerCount(); float[] points=new float[count*6];
        for(int i=0;i<count;i++) {
            points[i*6]=event.getPointerId(i); points[i*6+1]=event.getX(i); points[i*6+2]=event.getY(i);
            points[i*6+3]=event.getPressure(i);
        }
        RTNLibGodot.getInstance().dispatchTouchEvent(windowName,action,event.getPointerId(event.getActionIndex()),count,points,false);
    }
    private void cancelTouches() {
        if(lastTouch!=null) { forward(lastTouch,MotionEvent.ACTION_CANCEL); lastTouch.recycle(); lastTouch=null; }
    }
    @SuppressLint("ClickableViewAccessibility")
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (!surfaceAvailable) return false;
        if(event.getActionMasked()==MotionEvent.ACTION_DOWN && getParent() != null) getParent().requestDisallowInterceptTouchEvent(true);
        forward(event,event.getActionMasked());
        if(lastTouch!=null) lastTouch.recycle();
        lastTouch = event.getActionMasked()==MotionEvent.ACTION_UP || event.getActionMasked()==MotionEvent.ACTION_CANCEL ? null : MotionEvent.obtain(event);
        return true;
    }
    @Override protected void onDetachedFromWindow() { cancelTouches(); surfaceAvailable = false; super.onDetachedFromWindow(); }
}
