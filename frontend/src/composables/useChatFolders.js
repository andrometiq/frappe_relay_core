import { coreApi } from '../services/coreApi'
import { chatFolderStore } from '../services/chatFolders'

const store = chatFolderStore(coreApi)

export function useChatFolders() {
  return store
}
