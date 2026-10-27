/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Regression tests for the AI function helpers.
//
// The tests cover the embedding result validation, the recovery of an
// embedding answer that arrives out of order and the Ollama request and
// response handling.

#include "gtest/gtest.h"
#include "lib/allocator/ob_arena.h"
#include "common/json_type/ob_json_common.h"
#include "sql/engine/expr/ob_expr_ai/ob_ai_func_utils.h"

using namespace oceanbase;
using namespace oceanbase::common;
using namespace oceanbase::sql;

namespace
{

class TestObOpenAIUtils : public ::testing::Test
{
public:
  void SetUp() override {}
  void TearDown() override {}

protected:
  // Build the body of an OpenAI style embedding answer.
  static int build_embedding_answer(ObArenaAllocator &allocator,
                                    ObJsonObject *&http_response,
                                    int64_t count,
                                    int64_t dimension,
                                    bool with_index)
  {
    int ret = OB_SUCCESS;
    ObJsonObject *response = nullptr;
    ObJsonArray *data_array = nullptr;
    if (OB_FAIL(ObAIFuncJsonUtils::get_json_object(allocator, response))) {
    } else if (OB_FAIL(ObAIFuncJsonUtils::get_json_array(allocator, data_array))) {
    } else {
      for (int64_t i = 0; OB_SUCC(ret) && i < count; i++) {
        ObJsonObject *item = nullptr;
        ObJsonArray *embedding = nullptr;
        if (OB_FAIL(ObAIFuncJsonUtils::get_json_object(allocator, item))) {
        } else if (OB_FAIL(ObAIFuncJsonUtils::get_json_array(allocator, embedding))) {
        } else {
          for (int64_t d = 0; OB_SUCC(ret) && d < dimension; d++) {
            ObJsonDouble *value = nullptr;
            if (OB_FAIL(ObAIFuncJsonUtils::get_json_double(allocator, 0.5, value))) {
            } else if (OB_FAIL(embedding->append(value))) {
            }
          }
        }
        if (OB_SUCC(ret)) {
          if (OB_FAIL(item->add("embedding", embedding))) {
          } else if (with_index) {
            ObJsonInt *index = nullptr;
            if (OB_FAIL(ObAIFuncJsonUtils::get_json_int(allocator, i, index))) {
            } else if (OB_FAIL(item->add("index", index))) {
            }
          }
        }
        if (OB_SUCC(ret)) {
          ret = data_array->append(item);
        }
      }
      if (OB_SUCC(ret)) {
        ret = response->add("data", data_array);
      }
      if (OB_SUCC(ret)) {
        http_response = response;
      }
    }
    return ret;
  }
};

TEST_F(TestObOpenAIUtils, embedding_vector_with_the_expected_dimension_is_valid)
{
  ObArenaAllocator allocator;
  ObJsonArray *embedding = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, embedding));
  for (int64_t i = 0; i < 4; i++) {
    ObJsonDouble *value = nullptr;
    ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_double(allocator, 0.25, value));
    ASSERT_EQ(OB_SUCCESS, embedding->append(value));
  }
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_vector(embedding, 4));
}

TEST_F(TestObOpenAIUtils, embedding_vector_with_a_wrong_dimension_is_rejected)
{
  ObArenaAllocator allocator;
  ObJsonArray *embedding = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, embedding));
  for (int64_t i = 0; i < 3; i++) {
    ObJsonDouble *value = nullptr;
    ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_double(allocator, 0.25, value));
    ASSERT_EQ(OB_SUCCESS, embedding->append(value));
  }
  ASSERT_NE(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_vector(embedding, 4));
}

TEST_F(TestObOpenAIUtils, embedding_vector_with_a_non_number_element_is_rejected)
{
  ObArenaAllocator allocator;
  ObJsonArray *embedding = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, embedding));
  ObJsonDouble *value = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_double(allocator, 0.25, value));
  ASSERT_EQ(OB_SUCCESS, embedding->append(value));
  ObJsonString *text = nullptr;
  ObString text_str("not a number");
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_string(allocator, text_str, text));
  ASSERT_EQ(OB_SUCCESS, embedding->append(text));
  ASSERT_NE(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_vector(embedding, 0));
}

TEST_F(TestObOpenAIUtils, embedding_vector_that_is_not_an_array_is_rejected)
{
  ObArenaAllocator allocator;
  ObJsonObject *obj = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_object(allocator, obj));
  ASSERT_NE(OB_SUCCESS, ObAIFuncJsonUtils::validate_embedding_vector(obj, 0));
}

TEST_F(TestObOpenAIUtils, out_of_order_embedding_answer_is_restored)
{
  ObArenaAllocator allocator;
  ObJsonObject *http_response = nullptr;
  ASSERT_EQ(OB_SUCCESS, build_embedding_answer(allocator, http_response, 3, 2, true));

  // Move the last element to the front, the index tells the caller where the
  // embedding belongs.
  ObJsonArray *data = static_cast<ObJsonArray *>(http_response->get_value("data"));
  ASSERT_NE(nullptr, data);
  ASSERT_EQ(3, data->element_count());
  ObJsonNode *last = data->get_value(2);
  ASSERT_NE(nullptr, last);

  ObAIFuncClient client;
  ObIJsonBase *result = nullptr;
  // The provider restores the order, the answer of the service is out of
  // order.
  ObOpenAIUtils::ObOpenAIEmbed provider;
  ObJsonObject *shuffled = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_object(allocator, shuffled));
  ObJsonArray *shuffled_data = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, shuffled_data));
  // item with index 2 first, then 0, then 1
  ASSERT_EQ(OB_SUCCESS, shuffled_data->append(data->get_value(2)));
  ASSERT_EQ(OB_SUCCESS, shuffled_data->append(data->get_value(0)));
  ASSERT_EQ(OB_SUCCESS, shuffled_data->append(data->get_value(1)));
  ASSERT_EQ(OB_SUCCESS, shuffled->add("data", shuffled_data));

  ASSERT_EQ(OB_SUCCESS, provider.parse_output(allocator, shuffled, result));
  ASSERT_NE(nullptr, result);
  ASSERT_EQ(ObJsonNodeType::J_ARRAY, result->json_type());
  ObJsonArray *result_array = static_cast<ObJsonArray *>(result);
  ASSERT_EQ(3, result_array->element_count());
  // The embedding of the input 0 is back at the first position.
  for (int64_t i = 0; i < 3; i++) {
    ASSERT_NE(nullptr, result_array->get_value(i));
    ASSERT_EQ(ObJsonNodeType::J_ARRAY, result_array->get_value(i)->json_type());
  }
}

TEST_F(TestObOpenAIUtils, embedding_answer_without_an_index_keeps_the_order)
{
  ObArenaAllocator allocator;
  ObJsonObject *http_response = nullptr;
  ASSERT_EQ(OB_SUCCESS, build_embedding_answer(allocator, http_response, 2, 2, false));

  ObAIFuncClient client;
  ObIJsonBase *result = nullptr;
  ObOpenAIUtils::ObOpenAIEmbed provider;
  ASSERT_EQ(OB_SUCCESS, provider.parse_output(allocator, http_response, result));
  ASSERT_NE(nullptr, result);
  ASSERT_EQ(2, static_cast<ObJsonArray *>(result)->element_count());
}

TEST_F(TestObOpenAIUtils, ollama_embedding_body_uses_the_native_protocol)
{
  ObArenaAllocator allocator;
  ObString model("mock-embedding");
  ObArray<ObString> contents;
  ObString first("a");
  ObString second("b");
  ASSERT_EQ(OB_SUCCESS, contents.push_back(first));
  ASSERT_EQ(OB_SUCCESS, contents.push_back(second));

  ObJsonObject *body = nullptr;
  ObOllamaUtils::ObOllamaEmbed provider;
  ASSERT_EQ(OB_SUCCESS, provider.get_body(allocator, model, contents, nullptr, body));
  ASSERT_NE(nullptr, body);
  // The native protocol carries the inputs under "input".
  ASSERT_NE(nullptr, body->get_value("input"));
  ASSERT_NE(nullptr, body->get_value("model"));
  ASSERT_EQ(nullptr, body->get_value("dimensions"));
}

TEST_F(TestObOpenAIUtils, ollama_embedding_answer_is_read_from_the_native_field)
{
  ObArenaAllocator allocator;
  ObJsonObject *response = nullptr;
  ObJsonArray *embeddings = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_object(allocator, response));
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, embeddings));
  ObJsonArray *one = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, one));
  ObJsonDouble *value = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_double(allocator, 0.5, value));
  ASSERT_EQ(OB_SUCCESS, one->append(value));
  ASSERT_EQ(OB_SUCCESS, embeddings->append(one));
  ASSERT_EQ(OB_SUCCESS, response->add("embeddings", embeddings));

  ObIJsonBase *result = nullptr;
  ObOllamaUtils::ObOllamaEmbed provider;
  ASSERT_EQ(OB_SUCCESS, provider.parse_output(allocator, response, result));
  ASSERT_NE(nullptr, result);
  ASSERT_EQ(1, static_cast<ObJsonArray *>(result)->element_count());
}

TEST_F(TestObOpenAIUtils, ollama_complete_body_uses_the_native_protocol)
{
  ObArenaAllocator allocator;
  ObString model("mock-completion");
  ObString prompt("");
  ObString content("hello");

  ObJsonObject *body = nullptr;
  ObOllamaUtils::ObOllamaComplete provider;
  ASSERT_EQ(OB_SUCCESS, provider.get_body(allocator, model, prompt, content, nullptr, body));
  ASSERT_NE(nullptr, body);
  // The native protocol carries the text under "prompt".
  ASSERT_NE(nullptr, body->get_value("prompt"));
  ASSERT_NE(nullptr, body->get_value("model"));
  ASSERT_EQ(nullptr, body->get_value("messages"));
}

TEST_F(TestObOpenAIUtils, ollama_header_is_empty)
{
  ObArenaAllocator allocator;
  ObArray<ObString> headers;
  ASSERT_EQ(OB_SUCCESS, ObOllamaUtils::get_header(allocator, headers));
  // The native protocol does not carry an authorization header.
  ASSERT_EQ(0, headers.count());
}

TEST_F(TestObOpenAIUtils, completion_config_with_a_non_numeric_member_is_rejected)
{
  ObArenaAllocator allocator;
  ObJsonObject *config = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_object(allocator, config));
  ObJsonString *text = nullptr;
  ObString text_str("hot");
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_string(allocator, text_str, text));
  ASSERT_EQ(OB_SUCCESS, config->add("temperature", text));
  ASSERT_NE(OB_SUCCESS, ObAIFuncUtils::check_complete_config(config));
}

TEST_F(TestObOpenAIUtils, completion_config_with_numeric_members_is_accepted)
{
  ObArenaAllocator allocator;
  ObJsonObject *config = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_object(allocator, config));
  ObJsonDouble *temperature = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_double(allocator, 0.5, temperature));
  ASSERT_EQ(OB_SUCCESS, config->add("temperature", temperature));
  ObJsonInt *max_tokens = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_int(allocator, 16, max_tokens));
  ASSERT_EQ(OB_SUCCESS, config->add("max_tokens", max_tokens));
  ASSERT_EQ(OB_SUCCESS, ObAIFuncUtils::check_complete_config(config));
}

TEST_F(TestObOpenAIUtils, empty_completion_answer_is_rejected)
{
  ObArenaAllocator allocator;
  ObJsonString *content = nullptr;
  ObString content_str("");
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_string(allocator, content_str, content));
  ASSERT_NE(OB_SUCCESS, ObAIFuncUtils::check_complete_result_not_empty(content));
}

TEST_F(TestObOpenAIUtils, completion_answer_with_a_text_is_accepted)
{
  ObArenaAllocator allocator;
  ObJsonString *content = nullptr;
  ObString content_str("hello");
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_string(allocator, content_str, content));
  ASSERT_EQ(OB_SUCCESS, ObAIFuncUtils::check_complete_result_not_empty(content));
}

} // namespace

int main(int argc, char **argv)
{
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
