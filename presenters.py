import logging

from datetime import datetime
from event_scheduler import EventScheduler


class WordLogConstructor:
    def __init__(self):
        self.text = ""

    def append(self, text):
        self.text += text

    def flush(self):
        logging.getLogger("uvicorn").info(self.text)
        self.text = ""


class ResultPresenter:

    def partial_result(self, words):
        pass

    def final_result(self, words):
        pass

    def segment_start(self):
        self.turn_start_time = datetime.utcnow()

    def segment_end(self):
        pass

    def new_turn(self):
        self.turn_start_time = datetime.utcnow()


def prettify(words, is_sentence_start):
    for word in words:
        if is_sentence_start:
            word["word"] = word["word"][0].upper() + word["word"][1:]
        is_sentence_start = False

        if word["word"][-1] in ".!?":
            is_sentence_start = True

    return words


class AbstractWordByWordPresenter(ResultPresenter):
    def __init__(self, word_delay_secs=3.0):
        self.word_delay = 2
        self.word_delay_secs = word_delay_secs
        self.current_words = []
        self.num_sent_words = 0
        self.is_sentence_start = True
        self.event_scheduler = EventScheduler()
        self.event_scheduler.start()
        self.last_word_send_time = 0

    def _send_word(self, word, is_final):
        word_output_time = self.turn_start_time.timestamp() + word["start"] + self.word_delay_secs
        if word_output_time < self.last_word_send_time:
            word_output_time = self.last_word_send_time + 0.1
        self.event_scheduler.enter(word_output_time - datetime.utcnow().timestamp(), priority=1,
                                   action=self._send_word_impl,
                                   arguments=(word, self.num_sent_words, self.turn_start_time, is_final))
        self.last_word_send_time = word_output_time

    def _send_word_impl(self, word, num_sent_words, turn_start_time, is_final):
        pass

    def partial_result(self, words):
        words = prettify(words, self.is_sentence_start)
        # print(words)

        if len(words) - self.word_delay > self.num_sent_words:
            for i in range(self.num_sent_words, len(words) - self.word_delay):
                try:
                    self._send_word(words[i], False)
                except Exception:
                    logging.error("Couldn't send word to output", exc_info=True)
                self.num_sent_words += 1

    def final_result(self, words):
        words = prettify(words, self.is_sentence_start)

        for i in range(self.num_sent_words, len(words)):
            try:
                self._send_word(words[i], i == len(words) - 1)
            except Exception:
                logging.error("Couldn't send word to output", exc_info=True)
            self.num_sent_words += 1

        self.num_sent_words = 0
        if len(words) > 0 and words[-1]["word"][-1] in list("!?.,"):
            self.is_sentence_start = True
        else:
            self.is_sentence_start = False

    def new_turn(self):
        super().new_turn()
        try:
            self._send_word({"word": "- ", "start": 0.0}, False)
        except Exception:
            logging.error("Couldn't send word to output", exc_info=True)
        self.is_sentence_start = True


class WordByWordPresenter(AbstractWordByWordPresenter):
    def __init__(self, word_delay_secs=3.0):
        super().__init__(word_delay_secs)
        self.output_stream = None
        self.logger = WordLogConstructor()

    def _send_word_impl(self, word, num_sent_words, turn_start_time, is_final):
        if num_sent_words > 0 and word["word"][0] not in list(",.!?"):
            # print(" ", end="")
            self.logger.append(" ")
            self.output_stream.write(" ")
        # print(word["word"], end="")
        self.logger.append(word["word"])
        self.output_stream.write(word["word"])
        if is_final:
            # print("")
            self.logger.flush()
            self.output_stream.write("\n")
