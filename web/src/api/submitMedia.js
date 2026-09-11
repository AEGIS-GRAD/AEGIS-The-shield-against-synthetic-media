/**
 * Submits a media file (video or audio) for deepfake detection analysis.
 * Currently isolated mock implementation simulating network latency and returning
 * a standardized detector response schema.
 *
 * Swap this mock implementation with a real fetch() call to the AEGIS orchestrator/gateway
 * endpoint (/api/video or /api/audio) when backend integration is ready.
 *
 * @param {File} file - User selected media file (Video or Audio)
 * @returns {Promise<{
 *   modality: string,
 *   score: number,
 *   verdict: string,
 *   confidence: number,
 *   model: string
 * }>}
 */
export async function submitMedia(file) {
  if (!file) {
    throw new Error("No media file provided for submission.");
  }

  // Determine media modality based on file MIME type
  const isAudio = file.type.startsWith("audio/");
  const modality = isAudio ? "audio" : "video";

  // Simulate network delay (1.5 seconds)
  await new Promise((resolve) => setTimeout(resolve, 1500));

  // Return mocked detector response matching standard AEGIS schema
  return {
    modality: modality,
    score: 0.42,
    verdict: "synthetic",
    confidence: 0.58,
    model: isAudio ? "aasist-v2" : "xception-ffpp",
  };
}
