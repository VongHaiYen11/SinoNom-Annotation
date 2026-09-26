const dialog = element.querySelector('dialog');
const openButton = element.querySelector('.preview-open');
const photo = element.querySelector('img');
let loadedSource = '';
const sync = () => {
  openButton.disabled = !props.value;
  // Start loading when the image is opened in the workflow, and reuse that
  // request on modal open and subsequent state updates for the same image.
  if (props.value && props.value !== loadedSource) {
    loadedSource = props.value;
    photo.src = loadedSource;
  }
};
openButton.addEventListener('click', () => {
  if (!props.value) return;
  dialog.showModal();
});
element.querySelector('.preview-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
watch('value', () => { dialog.close(); sync(); });
sync();
