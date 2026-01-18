// Sidebar collapse state persistence for Quarto book
// Adapted from tocmenu.js architecture (Franklin.jl site)
// Uses sessionStorage to remember sidebar state during browser session

document.addEventListener('DOMContentLoaded', function() {
  console.log("Handling sidebar section state");

  // Get all collapsible sidebar sections
  const sidebarSections = document.querySelectorAll('.sidebar-section');

  // Restore saved state from sessionStorage
  let savedStates = JSON.parse(sessionStorage.getItem("sidebarSectionStates"));

  if (savedStates != null) {
    savedStates.forEach(sectionState => {
      const sectionElement = document.getElementById(sectionState.id);
      if (sectionElement) {
        const chevron = sectionElement.closest('.sidebar-item-section')?.querySelector('.bi-chevron-right');

        if (sectionState.collapsed) {
          // Collapse the section
          sectionElement.classList.remove('show');
          if (chevron) {
            chevron.classList.remove('rotateChevron');
          }
        } else {
          // Expand the section
          sectionElement.classList.add('show');
          if (chevron) {
            chevron.classList.add('rotateChevron');
          }
        }
      }
    });
  }

  // Listen to all sidebar section toggles
  sidebarSections.forEach(section => {
    section.addEventListener('hidden.bs.collapse', function() {
      saveSectionState(this.id, true);
    });

    section.addEventListener('shown.bs.collapse', function() {
      saveSectionState(this.id, false);
    });
  });

  function saveSectionState(sectionId, isCollapsed) {
    let savedStates = JSON.parse(sessionStorage.getItem("sidebarSectionStates"));

    const stateItem = {
      id: sectionId,
      collapsed: isCollapsed
    };

    if (savedStates == null) {
      savedStates = [stateItem];
      sessionStorage.setItem("sidebarSectionStates", JSON.stringify(savedStates));
      return;
    }

    let idx = savedStates.findIndex(x => x.id === sectionId);

    if (idx != -1) {
      // Update existing item
      savedStates[idx] = stateItem;
    } else {
      // Add new item
      savedStates.push(stateItem);
    }

    sessionStorage.setItem("sidebarSectionStates", JSON.stringify(savedStates));
  }
});
