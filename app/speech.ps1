# Local speech synthesis with the Windows voice's own timed viseme events.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @'
using System;
using System.IO;
using System.Collections.Generic;
using System.Speech.Synthesis;
using System.Speech.AudioFormat;
public class MouthCue { public double time; public double duration; public int id; }
public class VoiceResult { public string audio; public string voice; public List<MouthCue> visemes = new List<MouthCue>(); }
public static class CortanaVoice {
 public static VoiceResult Render(string text, int rate) {
  var result = new VoiceResult();
  using(var synth = new SpeechSynthesizer()) using(var stream = new MemoryStream()) {
   foreach(var voice in synth.GetInstalledVoices()) {
    if(voice.Enabled && voice.VoiceInfo.Gender == VoiceGender.Female) { synth.SelectVoice(voice.VoiceInfo.Name); break; }
   }
   synth.Rate = Math.Max(-3,Math.Min(3,rate));
   result.voice = synth.Voice.Name;
   synth.VisemeReached += (sender,e) => result.visemes.Add(new MouthCue { time=e.AudioPosition.TotalSeconds, duration=e.Duration.TotalSeconds, id=e.Viseme });
   synth.SetOutputToAudioStream(stream,new SpeechAudioFormatInfo(16000,AudioBitsPerSample.Sixteen,AudioChannel.Mono));
   synth.Speak(text);
   synth.SetOutputToNull();
   byte[] pcm=stream.ToArray();
   using(var wave=new MemoryStream()) using(var writer=new BinaryWriter(wave)) {
    writer.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));writer.Write(36+pcm.Length);
    writer.Write(System.Text.Encoding.ASCII.GetBytes("WAVEfmt "));writer.Write(16);
    writer.Write((short)1);writer.Write((short)1);writer.Write(16000);writer.Write(32000);
    writer.Write((short)2);writer.Write((short)16);writer.Write(System.Text.Encoding.ASCII.GetBytes("data"));writer.Write(pcm.Length);writer.Write(pcm);
    result.audio=Convert.ToBase64String(wave.ToArray());
   }
  }
  return result;
 }
}
'@
[CortanaVoice]::Render([string]$request.text,[int]$request.rate) | ConvertTo-Json -Depth 5 -Compress
