import { reactive } from 'vue';

export const historyStore = reactive({
  records: [],
  searchText: '',
  pendingExecutionId: '',
  selectedExecutionId: '',
  loading: false,
  error: '',
});
