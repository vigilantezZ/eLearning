/**
 * BMP CBT Exam Room Interactive Engine
 * Handles real-time subtest timer, question navigation, instantaneous autosave, and transitions.
 */

class CBTEngine {
  constructor(config) {
    this.sessionId = config.sessionId;
    this.packageId = config.packageId;
    this.remainingSeconds = config.remainingSeconds;
    this.totalQuestions = config.totalQuestions;
    this.menuUrl = config.menuUrl;
    this.autosaveUrl = config.autosaveUrl || '/api/cbt/autosave';

    this.currentQuestionIndex = 0;
    this.timerInterval = null;
    this.debounceTimer = null;
    this.pendingSave = null; // isian answer waiting for debounce
    this.inFlightSaves = new Set();

    this.initElements();
    this.initTimer();
    this.initEvents();
    this.showQuestion(0);
  }

  initElements() {
    this.timerDisplay = document.getElementById('timer-display');
    this.timerContainer = document.getElementById('cbt-timer-container');
    this.prevBtn = document.getElementById('btn-prev-q');
    this.nextBtn = document.getElementById('btn-next-q');
    this.doubtfulCheck = document.getElementById('check-doubtful');
    this.autosaveStatus = document.getElementById('autosave-status');
    this.questionCards = document.querySelectorAll('.cbt-question-card');
    this.paletteButtons = document.querySelectorAll('.palette-btn');
  }

  initTimer() {
    this.updateTimerDisplay();
    this.timerInterval = setInterval(() => {
      this.remainingSeconds--;
      this.updateTimerDisplay();

      if (this.remainingSeconds <= 300) {
        // Less than 5 minutes
        if (this.timerContainer) {
          this.timerContainer.classList.add('timer-warning');
        }
      }

      if (this.remainingSeconds <= 0) {
        clearInterval(this.timerInterval);
        this.onTimerExpired();
      }
    }, 1000);
  }

  updateTimerDisplay() {
    if (!this.timerDisplay) return;
    const hours = Math.floor(this.remainingSeconds / 3600);
    const minutes = Math.floor((this.remainingSeconds % 3600) / 60);
    const seconds = this.remainingSeconds % 60;

    let timeStr = '';
    if (hours > 0) {
      timeStr = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    } else {
      timeStr = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }
    this.timerDisplay.innerText = timeStr;
  }

  async onTimerExpired() {
    await this.flushAutosave();
    alert('Waktu untuk subtes ini telah habis! Jawaban Anda sudah tersimpan dan subtes ini dikunci. Anda akan kembali ke menu pilih subtes.');
    window.location.href = this.menuUrl;
  }

  async flushAutosave() {
    if (this.pendingSave) {
      clearTimeout(this.debounceTimer);
      const { qId, getValue } = this.pendingSave;
      this.pendingSave = null;
      this.triggerAutosave(qId, getValue());
    }
    await Promise.allSettled([...this.inFlightSaves]);
  }

  initEvents() {
    // Finish subtest: make sure pending answers reach the server before leaving
    const finishForm = document.getElementById('finish-subtest-form');
    if (finishForm) {
      finishForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const unanswered = [...this.paletteButtons].filter(
          (btn) => !btn.classList.contains('answered') && !btn.classList.contains('doubtful')
        ).length;
        let message = 'Selesaikan subtes ini dan kembali ke menu? Subtes yang sudah selesai tidak dapat dibuka kembali.';
        if (unanswered > 0) {
          message = `Masih ada ${unanswered} soal yang belum terisi. ` + message;
        }
        if (!confirm(message)) return;
        await this.flushAutosave();
        clearInterval(this.timerInterval);
        finishForm.submit();
      });
    }

    // Navigation buttons
    if (this.prevBtn) {
      this.prevBtn.addEventListener('click', () => {
        if (this.currentQuestionIndex > 0) {
          this.showQuestion(this.currentQuestionIndex - 1);
        }
      });
    }

    if (this.nextBtn) {
      this.nextBtn.addEventListener('click', () => {
        if (this.currentQuestionIndex < this.totalQuestions - 1) {
          this.showQuestion(this.currentQuestionIndex + 1);
        }
      });
    }

    // Palette clicks
    this.paletteButtons.forEach((btn, index) => {
      btn.addEventListener('click', () => {
        this.showQuestion(index);
      });
    });

    // Option interactions per card
    this.questionCards.forEach((card) => {
      const qId = card.dataset.questionId;
      const qType = card.dataset.questionType;

      if (qType === 'pg') {
        const optionItems = card.querySelectorAll('.option-item-pg');
        optionItems.forEach((opt) => {
          opt.addEventListener('click', () => {
            optionItems.forEach((o) => o.classList.remove('selected'));
            opt.classList.add('selected');
            const radio = opt.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;

            this.triggerAutosave(qId, opt.dataset.key);
          });
        });
      } else if (qType === 'pg_kompleks') {
        const optionItems = card.querySelectorAll('.option-item-kompleks');
        optionItems.forEach((opt) => {
          opt.addEventListener('click', (e) => {
            const checkbox = opt.querySelector('input[type="checkbox"]');
            if (e.target !== checkbox) {
              checkbox.checked = !checkbox.checked;
            }
            if (checkbox.checked) {
              opt.classList.add('selected');
            } else {
              opt.classList.remove('selected');
            }

            // Gather all checked keys
            const checkedKeys = [];
            card.querySelectorAll('.option-item-kompleks input[type="checkbox"]:checked').forEach((cb) => {
              checkedKeys.push(cb.value);
            });
            this.triggerAutosave(qId, checkedKeys);
          });
        });
      } else if (qType === 'isian') {
        const textInput = card.querySelector('.isian-input');
        if (textInput) {
          textInput.addEventListener('input', () => {
            clearTimeout(this.debounceTimer);
            this.pendingSave = { qId, getValue: () => textInput.value.trim() };
            this.debounceTimer = setTimeout(() => {
              this.pendingSave = null;
              this.triggerAutosave(qId, textInput.value.trim());
            }, 500);
          });
          textInput.addEventListener('blur', () => {
            if (this.pendingSave && this.pendingSave.qId === qId) {
              clearTimeout(this.debounceTimer);
              this.pendingSave = null;
            }
            this.triggerAutosave(qId, textInput.value.trim());
          });
        }
      }
    });

    // Doubtful checkbox event
    if (this.doubtfulCheck) {
      this.doubtfulCheck.addEventListener('change', () => {
        const activeCard = this.questionCards[this.currentQuestionIndex];
        if (!activeCard) return;
        const qId = activeCard.dataset.questionId;
        const currentAnswer = this.getCurrentCardAnswer(activeCard);
        this.triggerAutosave(qId, currentAnswer, this.doubtfulCheck.checked);
      });
    }
  }

  showQuestion(index) {
    if (index < 0 || index >= this.totalQuestions) return;
    this.currentQuestionIndex = index;

    // Show active card, hide others
    this.questionCards.forEach((card, idx) => {
      card.style.display = idx === index ? 'block' : 'none';
    });

    // Update palette active states
    this.paletteButtons.forEach((btn, idx) => {
      if (idx === index) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Update Doubtful checkbox for active card
    const activeCard = this.questionCards[index];
    if (activeCard && this.doubtfulCheck) {
      const isDoubtful = activeCard.dataset.isDoubtful === 'true';
      this.doubtfulCheck.checked = isDoubtful;
    }

    // Prev/Next buttons state
    if (this.prevBtn) {
      this.prevBtn.disabled = index === 0;
    }
    if (this.nextBtn) {
      if (index === this.totalQuestions - 1) {
        this.nextBtn.disabled = true;
        this.nextBtn.innerHTML = 'Soal Terakhir <i class="fas fa-check"></i>';
      } else {
        this.nextBtn.disabled = false;
        this.nextBtn.innerHTML = 'Soal Berikutnya <i class="fas fa-arrow-right"></i>';
      }
    }

    // Scroll slightly if user was far down
    if (window.scrollY > 150) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // Typeset math if MathJax exists
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise().catch((err) => console.log('MathJax error:', err));
    }
  }

  getCurrentCardAnswer(card) {
    const qType = card.dataset.questionType;
    if (qType === 'pg') {
      const selected = card.querySelector('.option-item-pg.selected');
      return selected ? selected.dataset.key : null;
    } else if (qType === 'pg_kompleks') {
      const keys = [];
      card.querySelectorAll('.option-item-kompleks input[type="checkbox"]:checked').forEach((cb) => {
        keys.push(cb.value);
      });
      return keys;
    } else if (qType === 'isian') {
      const input = card.querySelector('.isian-input');
      return input ? input.value.trim() : null;
    }
    return null;
  }

  triggerAutosave(questionId, answerValue, isDoubtful = null) {
    const request = this.sendAutosave(questionId, answerValue, isDoubtful);
    this.inFlightSaves.add(request);
    request.finally(() => this.inFlightSaves.delete(request));
    return request;
  }

  async sendAutosave(questionId, answerValue, isDoubtful = null) {
    const activeCard = this.questionCards[this.currentQuestionIndex];
    if (isDoubtful === null && activeCard) {
      isDoubtful = activeCard.dataset.isDoubtful === 'true';
    }

    if (this.autosaveStatus) {
      this.autosaveStatus.innerHTML = '<span class="text-muted"><i class="fas fa-spinner fa-spin"></i> Menyimpan...</span>';
    }

    try {
      const res = await fetch(this.autosaveUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.sessionId,
          question_id: parseInt(questionId),
          user_answer: answerValue,
          is_marked_doubtful: isDoubtful
        })
      });

      const data = await res.json();
      if (data.status === 'success') {
        if (this.autosaveStatus) {
          this.autosaveStatus.innerHTML = '<span class="text-success"><i class="fas fa-check-circle"></i> Jawaban tersimpan</span>';
        }

        // Update card metadata
        if (activeCard) {
          activeCard.dataset.isDoubtful = isDoubtful ? 'true' : 'false';
        }

        // Update palette button styling
        const paletteBtn = document.querySelector(`.palette-btn[data-question-id="${questionId}"]`);
        if (paletteBtn) {
          if (isDoubtful) {
            paletteBtn.classList.add('doubtful');
            paletteBtn.classList.remove('answered');
          } else if (data.has_answer) {
            paletteBtn.classList.add('answered');
            paletteBtn.classList.remove('doubtful');
          } else {
            paletteBtn.classList.remove('answered', 'doubtful');
          }
        }
      } else if (this.autosaveStatus) {
        // e.g. subtest already locked by the server
        this.autosaveStatus.innerHTML = '<span class="text-danger"><i class="fas fa-lock"></i> Jawaban tidak tersimpan: subtes sudah dikunci</span>';
      }
    } catch (err) {
      console.error('Autosave error:', err);
      if (this.autosaveStatus) {
        this.autosaveStatus.innerHTML = '<span class="text-danger"><i class="fas fa-exclamation-triangle"></i> Gagal menyimpan otomatis</span>';
      }
    }
  }
}

window.CBTEngine = CBTEngine;
