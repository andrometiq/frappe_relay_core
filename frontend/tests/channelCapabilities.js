import { ref } from 'vue'

const audio = ['audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/aac']
// The WhatsApp entry that api.capabilities returns for an account with templates and forms.
export const whatsappCapabilities = {
  enabled_channels: ['WhatsApp'],
  channels: {
    WhatsApp: {
      text: true, max_text_length: 4096, max_caption_length: 1024,
      media: { photo: ['image/jpeg', 'image/png'], video: ['video/mp4'], audio, voice: audio,
        document: ['application/pdf', 'text/plain'], sticker: ['image/webp'] },
      location: true, contacts: true, reply_quote: true, reactions: true, edits: false,
      read_receipts: true, group_receipts: true, templates: true, reply_window_hours: 24,
      bulk_campaigns: true, forms: true, voice_calls: true, groups: true, topics: false,
      email_threading: false, ai_automation: true, saved_replies: true,
    },
  },
}

// Stand-in for inject('relayCapabilities') when a test evaluates a composable outside a component.
export const injectCapabilities = () => ref(whatsappCapabilities)
