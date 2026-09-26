const dialog = element.querySelector('dialog');
const openButton = element.querySelector('.preview-open');
const photo = element.querySelector('img');
const sync = () => { openButton.disabled = !props.value; };
openButton.addEventListener('click', () => {
  if (!props.value) return;
  photo.src = props.value;
  dialog.showModal();
});
element.querySelector('.preview-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
watch('value', () => { dialog.close(); sync(); });
sync();
