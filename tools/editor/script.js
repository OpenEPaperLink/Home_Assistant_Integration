// State object holding all settings
let configState = {
  header: {
    text: 'Eetlijst',
    font_size: 40,
    color: '#FFFFFF'
  },
  style: {
    background_color: '#000000',
    date_format: '%a %d-%m'
  }
};

// Render accordion UI from configState
function renderAccordionUI() {
  const container = document.getElementById('accordion-container');
  container.innerHTML = '';
  Object.keys(configState).forEach(sectionKey => {
    const section = document.createElement('div');
    section.className = 'accordion-item';

    const header = document.createElement('div');
    header.className = 'accordion-header';
    header.textContent = sectionKey.charAt(0).toUpperCase() + sectionKey.slice(1);
    header.onclick = () => section.classList.toggle('open');

    const content = document.createElement('div');
    content.className = 'accordion-content';

    Object.keys(configState[sectionKey]).forEach(optKey => {
      const value = configState[sectionKey][optKey];
      const label = document.createElement('label');
      label.textContent = optKey + ': ';

      const input = document.createElement('input');
      if (optKey.includes('color')) {
        input.type = 'color';
      } else if (typeof value === 'number') {
        input.type = 'number';
      } else {
        input.type = 'text';
      }
      input.id = sectionKey + '-' + optKey;
      input.value = value;
      input.onchange = () => {
        const val = input.type === 'number' ? Number(input.value) : input.value;
        configState[sectionKey][optKey] = val;
        updateGeneratedYaml();
      };

      label.appendChild(input);
      content.appendChild(label);
    });

    section.appendChild(header);
    section.appendChild(content);
    container.appendChild(section);
  });
}

// Convert state to YAML and update textarea
function updateGeneratedYaml() {
  const yaml = jsyaml.dump(configState);
  document.getElementById('yaml-output').value = yaml;
}

// Send YAML to backend and display result
async function generateImage() {
  const yamlText = document.getElementById('yaml-output').value;
  const data = new FormData();
  data.append('yaml_data', yamlText);
  const resp = await fetch('/draw', {
    method: 'POST',
    body: data
  });
  if (resp.ok) {
    const imgData = await resp.text();
    document.getElementById('preview-image').src = imgData;
  }
}

document.getElementById('generate-btn').onclick = generateImage;

// Initialize UI
renderAccordionUI();
updateGeneratedYaml();
