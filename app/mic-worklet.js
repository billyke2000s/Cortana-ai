// Capture microphone samples without blocking the phone's interface thread.
class CortanaCapture extends AudioWorkletProcessor {
 constructor(){super();this.buffer=new Float32Array(2048);this.offset=0;}
 process(inputs,outputs){
  const input=inputs[0]?.[0];
  if(input){for(const sample of input){this.buffer[this.offset++]=sample;if(this.offset===this.buffer.length){this.port.postMessage(this.buffer,[this.buffer.buffer]);this.buffer=new Float32Array(2048);this.offset=0;}}}
  return true;
 }
}
registerProcessor('cortana-capture',CortanaCapture);
