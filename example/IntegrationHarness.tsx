/* eslint-disable no-void -- UI handlers intentionally consume handled promises. */
import React, {useEffect, useRef, useState} from 'react';
import {AppState, Button, DevSettings, Modal, StyleSheet, Text, TextInput, View} from 'react-native';
import {RTNGodot, RTNGodotView, runOnGodotThread} from '@borndotcom/react-native-godot';
import {scheduleOnRN} from 'react-native-worklets';
import {bundleDirectory} from 'expo-file-system/legacy';

export default function IntegrationHarness() {
  const [status, setStatus] = useState('Ready to start');
  const [attached, setAttached] = useState(true);
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [event, setEvent] = useState('No scene event yet');
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active' && !sheet) RTNGodot.resume(); else RTNGodot.pause();
    });
    if (sheet) RTNGodot.pause();
    else RTNGodot.resume();
    return () => subscription.remove();
  }, [sheet]);
  const load = (variant: 'a' | 'b') => {
    const name = variant === 'a' ? 'GodotTest' : 'GodotTest2';
    const path = decodeURIComponent(`${bundleDirectory}${name}.pck`.replace(/^file:\/\//, ''));
    const operation = async () => {
      RTNGodot.resume();
      await runOnGodotThread(() => {
        'worklet';
        if (RTNGodot.getInstance()) RTNGodot.destroyInstance();
        if (!RTNGodot.createInstance(['--main-pack', path, '--display-driver', 'embedded', '--rendering-driver', 'metal', '--rendering-method', 'mobile', '--audio-driver', 'Dummy'])) {
          throw new Error('Engine creation failed');
        }
      });
      // Let the engine load the scene before reading its state.
      for (let attempt = 0; attempt < 100; attempt++) {
        const result = await runOnGodotThread(() => {
          'worklet';
          const api = RTNGodot.API();
          const scene = api.Engine.get_main_loop().get_root().find_child('Harness', true, false);
          if (!scene) return null;
          const sceneStatus = JSON.parse(String(scene.status_json()));
          if (sceneStatus.frames < 3) return null;
          const callback = (payload: unknown) => {
            'worklet';
            scheduleOnRN(setEvent, String(payload));
          };
          scene.host_event.connect(callback);
          return {scene: sceneStatus, engine: api.Engine.get_version_info().get('string'), native: RTNGodot.getSessionStatus()};
        });
        if (result) return result;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error('Scene startup timed out');
    };
    const result = queue.current.then(operation);
    queue.current = result.catch(() => {});
    return result;
  };
  const run = async (cycles: number) => {
    if (busy) return;
    setBusy(true);
    try {
      for (let cycle = 0; cycle < cycles; cycle++) {
        const result = await load(cycle % 2 === 0 ? 'a' : 'b');
        const message = JSON.stringify({cycle: cycle + 1, ...result});
        console.info('[IntegrationHarness]', message);
        setStatus(message);
      }
    } catch (error) {setStatus(String(error));}
    finally {setBusy(false);}
  };
  return <View style={styles.root}>
    {attached ? <RTNGodotView style={StyleSheet.absoluteFill} /> : null}
    <View style={styles.controls}>
      <Text selectable>{status}</Text>
      <Text accessibilityLabel={`Scene event: ${event}`}>{event}</Text>
      <TextInput accessibilityLabel="Native input" placeholder="Type while the world runs" style={styles.input} />
      <Button title="Load blue pack" disabled={busy} onPress={() => {void load('a').then(x => setStatus(JSON.stringify(x))).catch(x => setStatus(String(x)));}} />
      <Button title="Load red pack" disabled={busy} onPress={() => {void load('b').then(x => setStatus(JSON.stringify(x))).catch(x => setStatus(String(x)));}} />
      <Button title="Run 20 pack/restart cycles" disabled={busy} onPress={() => {void run(20);}} />
      <Button title={attached ? 'Detach surface' : 'Attach surface'} onPress={() => setAttached(!attached)} />
      <Button title="Reload JavaScript runtime" onPress={() => DevSettings.reload()} />
      <Button title="Check scene event round trip" onPress={() => {void runOnGodotThread(() => {
        'worklet';
        const scene = RTNGodot.API().Engine.get_main_loop().get_root().find_child('Harness', true, false);
        scene.echo_event('你好，G 🐈');
      }).catch(error => setStatus(String(error)));}} />
      <Button title="Open native sheet" onPress={() => setSheet(true)} />
    </View>
    <Modal visible={sheet} presentationStyle="pageSheet" onRequestClose={() => setSheet(false)}>
      <View style={styles.controls}><Text>The world is paused.</Text><Button title="Return" onPress={() => setSheet(false)} /></View>
    </Modal>
  </View>;
}
const styles = StyleSheet.create({root: {flex: 1}, controls: {marginTop: 60, padding: 16, backgroundColor: 'white'}, input: {borderWidth: 1, padding: 12}});
