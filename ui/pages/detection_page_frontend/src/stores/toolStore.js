import { reactive } from 'vue';

export const toolStore = reactive({
  tools: [],
  selectedToolId: '',
  selectedDescriptor: null,
  loading: false,
});
